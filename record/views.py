import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import user_is_approved
from .models import AnesthesiaRecord, FreeTextNote, AnesthesiaCase, RecordTemplate

# 기본 행(HR/SBP/DBP/SpO2)은 모델 컬럼, 나머지는 extra_vitals(JSON)에 저장
BASE_FIELDS = ('hr', 'sbp', 'dbp', 'spo2')
ROW_GROUPS = ('vital', 'gas', 'fluid', 'output', 'drug', 'etc')
# 서식에 저장되는 케이스 정보 (환자 식별정보·시각은 제외)
TEMPLATE_INFO_KEYS = ('operation', 'surgeon', 'anesthesiologist', 'anesth_type', 'asa', 'asa_e', 'anesth_detail', 'interval')
MAX_TEMPLATES = 50


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


def _template_to_dict(tpl):
    return {'id': tpl.id, 'name': tpl.name, 'data': tpl.data or {}}


def _templates(user):
    return [_template_to_dict(t) for t in RecordTemplate.objects.filter(user=user)]


def _page_state(user):
    case = AnesthesiaCase.objects.filter(user=user).first()
    note = FreeTextNote.objects.filter(user=user).first()
    records = list(AnesthesiaRecord.objects.filter(user=user).order_by('timestamp', 'id'))
    case_dict = _case_to_dict(case) if case else {'info': {}, 'events': [], 'rows': []}
    note_text = note.content if note else ''
    # 작성 중인 기록이 하나도 없으면 새 케이스로 시작
    is_new = not (records or note_text.strip() or case_dict['events']
                  or any(str(v).strip() for v in case_dict['info'].values()))
    return {
        'case': case_dict,
        'note': note_text,
        'records': [_record_to_dict(r) for r in records],
        'is_new': is_new,
        'today': timezone.localdate().isoformat(),
        'templates': _templates(user),
    }


def _parse_local_dt(value):
    """'YYYY-MM-DDTHH:MM' (Asia/Seoul 로컬) -> aware datetime."""
    if not value:
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
        return int(round(float(value)))
    except ValueError:
        raise ValueError(value)


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
            cleaned[key] = int(num) if num.is_integer() and '.' not in text else num
        except ValueError:
            cleaned[key] = text
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
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': '잘못된 요청 형식입니다.'}, status=400)

    user = request.user
    patient_id = str(payload.get('case', {}).get('info', {}).get('patient_id', '') or 'unknown')[:50]
    errors = []
    parsed_columns = []

    for idx, col in enumerate(payload.get('columns', []) or []):
        ts = _parse_local_dt(col.get('timestamp'))
        if ts is None:
            errors.append(f'{idx + 1}번째 컬럼: 시간이 올바르지 않습니다.')
            continue
        values = {}
        for field in BASE_FIELDS:
            try:
                values[field] = _parse_int(col.get(field))
            except ValueError as exc:
                errors.append(f'{col.get("timestamp", "")[11:16]} {field.upper()}: 숫자가 아닙니다 ({exc}).')
        parsed_columns.append((col, ts, values))

    if errors:
        return JsonResponse({'ok': False, 'error': '\n'.join(errors)}, status=400)

    with transaction.atomic():
        case, _ = AnesthesiaCase.objects.select_for_update().get_or_create(user=user)
        case_data = payload.get('case', {}) or {}
        case.info = _clean_info(case_data.get('info', {}))
        case.events = _clean_events(case_data.get('events', []))
        case.rows = _clean_rows(case_data.get('rows', []))
        case.save()

        if 'note' in payload:
            note = FreeTextNote.objects.filter(user=user).first() or FreeTextNote(user=user)
            note.content = str(payload.get('note') or '')
            note.save()

        deleted = [int(i) for i in payload.get('deleted', []) or [] if str(i).lstrip('-').isdigit() and int(i) > 0]
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


def _clean_template_data(data):
    data = data if isinstance(data, dict) else {}
    info = _clean_info(data.get('info', {}))
    return {
        'info': {k: info[k] for k in TEMPLATE_INFO_KEYS if info.get(k)},
        'rows': _clean_rows(data.get('rows', [])),
        'note': str(data.get('note') or '')[:10000],
    }


@login_required
@user_is_approved
@require_POST
def save_template(request):
    """현재 내용을 서식으로 저장. 같은 이름이 있으면 덮어씀."""
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': '잘못된 요청 형식입니다.'}, status=400)
    name = str(payload.get('name') or '').strip()[:60]
    if not name:
        return JsonResponse({'ok': False, 'error': '서식 이름을 입력하세요.'}, status=400)
    user = request.user
    tpl = RecordTemplate.objects.filter(user=user, name=name).first()
    if tpl is None and RecordTemplate.objects.filter(user=user).count() >= MAX_TEMPLATES:
        return JsonResponse({'ok': False, 'error': f'서식은 최대 {MAX_TEMPLATES}개까지 저장할 수 있습니다.'}, status=400)
    tpl = tpl or RecordTemplate(user=user, name=name)
    tpl.data = _clean_template_data(payload.get('data'))
    tpl.save()
    return JsonResponse({'ok': True, 'id': tpl.id, 'templates': _templates(user)})


@login_required
@user_is_approved
@require_POST
def delete_template(request, template_id):
    tpl = get_object_or_404(RecordTemplate, pk=template_id, user=request.user)
    tpl.delete()
    return JsonResponse({'ok': True, 'templates': _templates(request.user)})


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
