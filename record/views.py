import json
import math
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import user_is_approved
from .models import AnesthesiaRecord, FreeTextNote, AnesthesiaCase

# 기본 행(HR/SBP/DBP/SpO2)은 모델 컬럼, 나머지는 extra_vitals(JSON)에 저장
BASE_FIELDS = ('hr', 'sbp', 'dbp', 'spo2')
ROW_GROUPS = ('vital', 'gas', 'fluid', 'output', 'drug', 'etc')
INT_MIN, INT_MAX = -2**31, 2**31 - 1


def _record_to_dict(record):
    ts = timezone.localtime(record.timestamp)
    return {
        'id': record.id,
        'timestamp': ts.strftime('%Y-%m-%dT%H:%M'),
        'hr': record.hr,
        'sbp': record.sbp,
        'dbp': record.dbp,
        'spo2': record.spo2,
        'extra_vitals': record.extra_vitals or {},
        'notes': record.additional_notes,
    }


def _case_to_dict(case):
    return {'info': case.info or {}, 'events': case.events or [], 'rows': case.rows or []}


def _page_state(user):
    case, _ = AnesthesiaCase.objects.get_or_create(user=user)
    note = FreeTextNote.objects.filter(user=user).first()
    records = AnesthesiaRecord.objects.filter(user=user).order_by('timestamp', 'id')
    return {
        'case': _case_to_dict(case),
        'note': note.content if note else '',
        'records': [_record_to_dict(r) for r in records],
    }


def _parse_local_dt(value):
    """'YYYY-MM-DDTHH:MM' (Asia/Seoul 로컬) -> aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        naive = datetime.strptime(value[:16], '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _parse_int(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == '':
        return None
    try:
        num = float(value)
    except ValueError:
        raise ValueError(value)
    # inf/nan 및 DB IntegerField 범위를 벗어나는 값은 500 대신 입력 오류로 처리
    if not math.isfinite(num) or not INT_MIN <= round(num) <= INT_MAX:
        raise ValueError(value)
    return int(round(num))


def _clean_extra(extra):
    cleaned = {}
    if not isinstance(extra, dict):
        return cleaned
    for key, value in extra.items():
        key = str(key).strip()[:50]
        if not key or value is None or str(value).strip() == '':
            continue
        text = str(value).strip()[:100]
        try:
            num = float(text)
        except ValueError:
            cleaned[key] = text
            continue
        if not math.isfinite(num):
            # NaN/Infinity는 JSON(DB)에 저장할 수 없으므로 문자열로 보존
            cleaned[key] = text
        else:
            cleaned[key] = int(num) if num.is_integer() and '.' not in text else num
    return cleaned


def _clean_rows(rows):
    cleaned, seen = [], set()
    reserved = {'HR', 'SBP', 'DBP', 'MBP', 'SPO2'}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str):
            row = {'name': row}
        if not isinstance(row, dict):
            continue
        name = str(row.get('name', '')).strip()[:50]
        if not name or name.upper() in reserved or name in seen:
            continue
        seen.add(name)
        group = row.get('group') if row.get('group') in ROW_GROUPS else 'etc'
        cleaned.append({'name': name, 'group': group, 'unit': str(row.get('unit', '')).strip()[:20]})
    return cleaned


def _clean_events(events):
    cleaned = []
    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict):
            continue
        label = str(ev.get('label', '')).strip()[:100]
        time = str(ev.get('time', '')).strip()[:16]
        if label and _parse_local_dt(time):
            cleaned.append({'time': time, 'label': label})
    cleaned.sort(key=lambda e: e['time'])
    return cleaned


def _clean_info(info):
    if not isinstance(info, dict):
        return {}
    return {str(k)[:50]: str(v).strip()[:300] for k, v in info.items() if v is not None}


@login_required
@user_is_approved
def anesthesia_record_view(request):
    return render(request, 'record/anesthesia_record.html', {'state': _page_state(request.user)})


@login_required
@user_is_approved
@require_POST
def save_all(request):
    """케이스 정보 + 기록(노트) + 모든 시간 컬럼을 한 번에 저장 (트랜잭션)."""
    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': '잘못된 요청 형식입니다.'}, status=400)

    case_data = payload.get('case') if isinstance(payload, dict) else None
    columns = payload.get('columns') if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not isinstance(case_data or {}, dict) or not isinstance(columns or [], list):
        return JsonResponse({'ok': False, 'error': '잘못된 요청 형식입니다.'}, status=400)
    case_data = case_data or {}
    info = case_data.get('info') if isinstance(case_data.get('info'), dict) else {}

    user = request.user
    patient_id = str(info.get('patient_id', '') or 'unknown')[:50]
    errors = []
    parsed_columns = []

    for idx, col in enumerate(columns or []):
        if not isinstance(col, dict):
            errors.append(f'{idx + 1}번째 컬럼: 형식이 올바르지 않습니다.')
            continue
        ts = _parse_local_dt(col.get('timestamp'))
        if ts is None:
            errors.append(f'{idx + 1}번째 컬럼: 시간이 올바르지 않습니다.')
            continue
        values = {}
        for field in BASE_FIELDS:
            try:
                values[field] = _parse_int(col.get(field))
            except ValueError as exc:
                errors.append(f'{col["timestamp"][11:16]} {field.upper()}: 숫자가 아닙니다 ({exc}).')
        parsed_columns.append((col, ts, values))

    if errors:
        return JsonResponse({'ok': False, 'error': '\n'.join(errors)}, status=400)

    with transaction.atomic():
        case, _ = AnesthesiaCase.objects.select_for_update().get_or_create(user=user)
        case.info = _clean_info(info)
        case.events = _clean_events(case_data.get('events', []))
        case.rows = _clean_rows(case_data.get('rows', []))
        case.save()

        if 'note' in payload:
            note = FreeTextNote.objects.filter(user=user).first() or FreeTextNote(user=user)
            note.content = str(payload.get('note') or '')
            note.save()

        deleted = payload.get('deleted') if isinstance(payload.get('deleted'), list) else []
        deleted = [int(i) for i in deleted if str(i).lstrip('-').isdigit() and int(i) > 0]
        if deleted:
            AnesthesiaRecord.objects.filter(user=user, id__in=deleted).delete()

        for col, ts, values in parsed_columns:
            record = None
            col_id = col.get('id')
            if isinstance(col_id, int) and col_id > 0:
                record = AnesthesiaRecord.objects.filter(user=user, id=col_id).first()
            if record is None:
                record = AnesthesiaRecord(user=user)
            record.patient_id = patient_id
            record.timestamp = ts
            for field, value in values.items():
                setattr(record, field, value)
            record.extra_vitals = _clean_extra(col.get('extra_vitals', {}))
            record.additional_notes = str(col.get('notes') or '')[:2000]
            record.save()

    return JsonResponse({'ok': True, 'state': _page_state(user)})


@login_required
@user_is_approved
@require_POST
def delete_record(request, record_id):
    record = get_object_or_404(AnesthesiaRecord, pk=record_id, user=request.user)
    record.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect('anesthesia_record')


@login_required
@user_is_approved
def reset_all(request):
    if request.method == "POST":
        AnesthesiaRecord.objects.filter(user=request.user).delete()
        FreeTextNote.objects.filter(user=request.user).delete()
        AnesthesiaCase.objects.filter(user=request.user).delete()
    return redirect('anesthesia_record')
