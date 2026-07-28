from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import SurgerySchedule
from .forms import ScheduleUploadForm
from collections import defaultdict
from dateutil import parser as date_parser
import openpyxl
import re
from io import BytesIO
from .models import SurgerySchedule, PatientMemo
from .gemini_client import extract_schedules_from_text, ScheduleExtractionError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json
import logging
from accounts.decorators import user_is_specially_approved

logger = logging.getLogger(__name__)

# Matches the registration/chart number gemini_client.py asks Gemini to put first in
# patient_info (e.g. "71203438 (M/42)"). Requiring 4+ digits avoids treating a stray
# short number as an id.
REGISTRATION_NUMBER_RE = re.compile(r"^(\d{4,})")

# Django model field -> max_length, used to defensively truncate whatever
# Gemini returns before it hits the DB (source files/layouts are arbitrary).
FIELD_MAX_LENGTHS = {
    "room": 10,
    "time_slot": 10,
    "surgery_name": 200,
    "department": 50,
    "surgeon": 50,
    "patient_name": 50,
    "patient_info": 20,
    "status": 50,
}


@login_required
@user_is_specially_approved
def schedule_dashboard(request):
    form = ScheduleUploadForm()
    error_message = None
    schedules = SurgerySchedule.objects.filter(user=request.user).order_by("date", "room", "time_slot")

    schedule_by_room = defaultdict(list)
    for schedule in schedules:
        schedule_by_room[schedule.room].append(schedule)

    # Build a summary dictionary for each room:
    summary_by_room = {}
    for room, schedules in schedule_by_room.items():
        summary = {'ongoing': None, 'pending': 0, 'finished': 0}
        for schedule in schedules:
            if schedule.status in ["진행중", "수술중"]:
                # pick the first ongoing surgery (if any)
                if summary['ongoing'] is None:
                    summary['ongoing'] = schedule
            elif schedule.status == "완료":
                summary['finished'] += 1
            else:
                summary['pending'] += 1
        summary_by_room[room] = summary

    if request.method == "POST":
        action = request.POST.get('action', 'replace')  # 'replace' 또는 'update'
        form = ScheduleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            try:
                source_text = extract_text_from_upload(uploaded_file)
                records = extract_schedules_from_text(source_text, uploaded_file.name)
                if action == 'replace':
                    SurgerySchedule.objects.filter(user=request.user).delete()
                    create_schedules_from_records(records, request.user)
                else:
                    existing_schedules = list(SurgerySchedule.objects.filter(user=request.user))
                    update_schedules_from_records(records, request.user, existing_schedules)
            except (ScheduleExtractionError, ValueError) as exc:
                error_message = str(exc)
            else:
                return redirect("schedule_dashboard")

    return render(request, "schedule/dashboard.html", {
        "schedule_by_room": dict(schedule_by_room),
        "summary_by_room": summary_by_room,
        "form": form,
        "error_message": error_message,
    })


def extract_text_from_upload(uploaded_file):
    """Turns an uploaded Excel/CSV/text file into a plain-text dump for Gemini to read."""
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()

    if name.endswith((".xlsx", ".xls")):
        try:
            workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True)
        except Exception as exc:
            raise ValueError("엑셀 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.") from exc
        lines = []
        for sheet in workbook.worksheets:
            lines.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if cell is None else str(cell) for cell in row]
                if any(cell.strip() for cell in cells):
                    lines.append("\t".join(cells))
        return "\n".join(lines)

    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일의 텍스트 인코딩을 해석할 수 없습니다.")


def _normalize_record(record):
    """Coerces one Gemini-returned record into values matching SurgerySchedule fields."""
    raw_date = record.get("date")
    try:
        parsed_date = date_parser.parse(str(raw_date), fuzzy=True).date()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ScheduleExtractionError(f"날짜를 해석할 수 없습니다: {raw_date!r}") from exc

    try:
        duration = int(float(record.get("duration") or 0))
    except (ValueError, TypeError):
        duration = 0

    data = {
        "date": parsed_date,
        "room": str(record.get("room") or "").strip(),
        "time_slot": str(record.get("time_slot") or "").strip(),
        "surgery_name": str(record.get("surgery_name") or "").strip(),
        "department": str(record.get("department") or "").strip(),
        "surgeon": str(record.get("surgeon") or "").strip(),
        "duration": duration,
        "patient_name": str(record.get("patient_name") or "").strip(),
        "patient_info": str(record.get("patient_info") or "").strip(),
        "status": str(record.get("status") or "예정").strip(),
    }
    for field, max_length in FIELD_MAX_LENGTHS.items():
        data[field] = data[field][:max_length]
    return data


def _has_identity(data):
    """False for a record with no room/time/patient at all - e.g. a "co-surgeon
    continuation" row some OR exports include (same surgery_name/duration as the row
    above, but every identifying field blank, just to record a second surgeon). There's
    nothing to display or match such a row against, and letting it through used to
    create phantom "no room" cards and, worse, could collide with a real case's
    _case_key and overwrite it. The extraction prompt now asks Gemini to fold these
    into the real row's surgeon field instead of emitting them, but we still filter
    defensively in case one slips through."""
    return bool(data["patient_name"] or data["room"] or data["time_slot"])


def create_schedules_from_records(records, user):
    """Gemini-extracted records -> new SurgerySchedule rows."""
    for raw_record in records:
        data = _normalize_record(raw_record)
        if not _has_identity(data):
            logger.warning("Skipping unidentifiable schedule record: %r", raw_record)
            continue
        SurgerySchedule.objects.create(user=user, **data)


def _registration_number(patient_info):
    """Pulls the leading digit run out of patient_info, if any (see
    REGISTRATION_NUMBER_RE). This is the strongest available matching signal - unlike a
    name or surgery name, Gemini only has to transcribe digits verbatim, not make a
    wording judgment, so it's far less prone to varying between two separate calls."""
    match = REGISTRATION_NUMBER_RE.match(patient_info or "")
    return match.group(1) if match else None


def _normalize_text(value):
    """Collapses internal whitespace and strips - cheap insurance against a stray
    double space or trailing space making two calls' output compare unequal for what's
    obviously the same text."""
    return re.sub(r"\s+", " ", value or "").strip()


def _case_key(patient_name, surgery_name, surgeon):
    """Identity used only to disambiguate when one patient has more than one case on
    file (see update_schedules_from_records) - normalized equality on (patient_name,
    surgery_name, surgeon)."""
    return (_normalize_text(patient_name), _normalize_text(surgery_name), _normalize_text(surgeon))


def _slot_key(date, room, time_slot):
    """Fallback identity for records with no patient name at all (e.g. a memo file that
    only lists times), keyed on (date, room, time_slot)."""
    return (date, _normalize_text(room), _normalize_text(time_slot))


def update_schedules_from_records(records, user, existing_schedules):
    """Gemini-extracted records -> synced SurgerySchedule rows for `user`.

    Each new record is matched against the existing rows in this order:
      1. registration number (_registration_number), if both sides have one - the
         strongest signal, since it's just digits Gemini has to transcribe verbatim;
      2. patient name alone, if exactly one existing (unclaimed) schedule has that name -
         deliberately NOT also requiring surgery_name/surgeon to match here. Real
         schedule exports can reword a surgery name or surgeon slightly between two
         uploads of "the same" case (translated vs Korean, abbreviated, punctuation),
         and requiring an exact match on top of the name turned out to make matching
         fail far too often in practice - which, combined with the delete-on-no-match
         step below, showed up as memos getting wiped on nearly every update;
      3. patient name plus surgery_name/surgeon (_case_key), only used to disambiguate
         when a patient has *more than one* case on file that day;
      4. (date, room, time_slot) (_slot_key), for records with no patient name at all.
    A match updates that row in place (same pk), so its memo is kept even if
    date/room/time/status (or surgery_name/surgeon wording) changed. A new record with
    no match is inserted fresh (no memo yet, as expected for a genuinely new case). An
    existing row with no match in the new upload is treated as no longer part of the
    schedule (cancelled, or just not in this file) and is deleted - PatientMemo cascades
    on delete, so its memo goes with it, per how this was asked to behave.
    """
    by_regnum = {}
    by_name = defaultdict(list)
    by_slot = {}
    for schedule in existing_schedules:
        regnum = _registration_number(schedule.patient_info)
        if regnum:
            by_regnum.setdefault(regnum, schedule)
        if schedule.patient_name:
            by_name[_normalize_text(schedule.patient_name)].append(schedule)
        else:
            by_slot[_slot_key(schedule.date, schedule.room, schedule.time_slot)] = schedule

    claimed_ids = set()
    matched_count = 0
    created_count = 0

    for raw_record in records:
        data = _normalize_record(raw_record)
        if not _has_identity(data):
            logger.warning("Skipping unidentifiable schedule record: %r", raw_record)
            continue

        schedule = None

        regnum = _registration_number(data["patient_info"])
        if regnum:
            candidate = by_regnum.get(regnum)
            if candidate is not None and candidate.id not in claimed_ids:
                schedule = candidate

        if schedule is None and data["patient_name"]:
            candidates = [s for s in by_name.get(_normalize_text(data["patient_name"]), []) if s.id not in claimed_ids]
            if len(candidates) == 1:
                schedule = candidates[0]
            elif len(candidates) > 1:
                key = _case_key(data["patient_name"], data["surgery_name"], data["surgeon"])
                for candidate in candidates:
                    if _case_key(candidate.patient_name, candidate.surgery_name, candidate.surgeon) == key:
                        schedule = candidate
                        break

        if schedule is None and not data["patient_name"]:
            candidate = by_slot.get(_slot_key(data["date"], data["room"], data["time_slot"]))
            if candidate is not None and candidate.id not in claimed_ids:
                schedule = candidate

        if schedule:
            claimed_ids.add(schedule.id)
            matched_count += 1
            changed = any(getattr(schedule, field) != value for field, value in data.items())
            if changed:
                for field, value in data.items():
                    setattr(schedule, field, value)
                schedule.save()
        else:
            created_count += 1
            SurgerySchedule.objects.create(user=user, **data)

    # Whatever wasn't claimed wasn't matched by anything in this upload - the case is no
    # longer part of the schedule, so remove it (and its memo along with it).
    stale = [schedule for schedule in existing_schedules if schedule.id not in claimed_ids]
    if stale:
        logger.warning(
            "update_schedules_from_records: deleting %d unmatched schedule(s) for user=%s: %s",
            len(stale), user,
            [(s.id, s.patient_name, s.surgery_name, s.surgeon, s.patient_info) for s in stale],
        )
        SurgerySchedule.objects.filter(id__in=[schedule.id for schedule in stale]).delete()

    logger.info(
        "update_schedules_from_records: user=%s matched=%d created=%d deleted=%d",
        user, matched_count, created_count, len(stale),
    )


@login_required
@user_is_specially_approved
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def handle_memo(request, schedule_id):
    try:
        schedule = SurgerySchedule.objects.get(id=schedule_id)
    except SurgerySchedule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)

    if request.method == "GET":
        memo = PatientMemo.objects.filter(schedule_id=schedule_id).first()
        return JsonResponse({
            'status': 'success',
            'content': memo.content if memo else ''
        })

    elif request.method == "POST":
        try:
            data = json.loads(request.body)
            content = data.get('content', '')

            memo, created = PatientMemo.objects.update_or_create(
                schedule=schedule,
                defaults={'content': content}
            )

            return JsonResponse({
                'status': 'success',
                'message': 'Memo saved successfully'
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Error saving memo: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
