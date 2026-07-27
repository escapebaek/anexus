from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import SurgerySchedule
from .forms import ScheduleUploadForm
from collections import defaultdict
from dateutil import parser as date_parser
import openpyxl
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
                if action == 'replace':
                    records = extract_schedules_from_text(source_text, uploaded_file.name)
                    SurgerySchedule.objects.filter(user=request.user).delete()
                    create_schedules_from_records(records, request.user)
                else:
                    existing_schedules = list(SurgerySchedule.objects.filter(user=request.user))
                    existing_payload = [_schedule_to_payload(s) for s in existing_schedules]
                    records = extract_schedules_from_text(
                        source_text, uploaded_file.name, existing_schedules=existing_payload
                    )
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
    create phantom "no room" cards and, worse, could steal an existing schedule's
    matched_existing_id and blank it out. The extraction prompt now asks Gemini to fold
    these into the real row's surgeon field instead of emitting them, but we still
    filter defensively in case one slips through."""
    return bool(data["patient_name"] or data["room"] or data["time_slot"])


def create_schedules_from_records(records, user):
    """Gemini-extracted records -> new SurgerySchedule rows."""
    for raw_record in records:
        data = _normalize_record(raw_record)
        if not _has_identity(data):
            logger.warning("Skipping unidentifiable schedule record: %r", raw_record)
            continue
        SurgerySchedule.objects.create(user=user, **data)


def _schedule_to_payload(schedule):
    """SurgerySchedule -> the minimal dict Gemini needs to match against it (see
    schedule/gemini_client.py). Includes "id" so a match can be reported back."""
    return {
        "id": schedule.id,
        "date": str(schedule.date),
        "room": schedule.room,
        "time_slot": schedule.time_slot,
        "surgery_name": schedule.surgery_name,
        "department": schedule.department,
        "surgeon": schedule.surgeon,
        "patient_name": schedule.patient_name,
        "patient_info": schedule.patient_info,
        "status": schedule.status,
    }


def _record_identity(patient_name, surgery_name, date, room, time_slot):
    """Fallback identity match, used only when Gemini didn't return a
    matched_existing_id for a record (e.g. it had no existing schedules to compare
    against, or genuinely couldn't tell). Keyed on (date, patient, surgery): date is
    kept so the same patient having the same-named procedure on a *different* day
    doesn't get merged into one row. Falls back further to the (date, room, time_slot)
    slot when there's no patient name to key off of (e.g. a memo file listing only
    times, no patient identifiers)."""
    if patient_name:
        return ("patient", date, patient_name, surgery_name)
    return ("slot", date, room, time_slot)


def update_schedules_from_records(records, user, existing_schedules):
    """Gemini-extracted records -> upserted SurgerySchedule rows.

    existing_schedules is the list of SurgerySchedule rows that was shown to Gemini
    (see _schedule_to_payload / gemini_client.extract_schedules_from_text). Each record
    is matched, in order of preference, to:
      1. the existing row Gemini pointed at via "matched_existing_id" - it saw both
         files and can tell "same case, reworded" from "actually a different case";
      2. an exact (date, patient_name, surgery_name) match, as a safety net for
         whichever records Gemini didn't confidently match;
      3. otherwise it's inserted as a new case.
    Matching onto an existing row updates it in place (same pk), so its memo is kept.

    Each existing row can only be claimed by ONE record per upload (tracked via
    `claimed`): without this, two records both pointing at the same
    matched_existing_id would update the same row twice, and the second write
    (e.g. a stray, mostly-blank record) would silently blank out the first's data -
    memo stays attached to the row, but the row itself looks broken/misplaced.
    """
    by_id = {schedule.id: schedule for schedule in existing_schedules}
    by_identity = {
        _record_identity(
            schedule.patient_name, schedule.surgery_name,
            schedule.date, schedule.room, schedule.time_slot,
        ): schedule
        for schedule in existing_schedules
    }
    claimed = set()

    for raw_record in records:
        data = _normalize_record(raw_record)
        if not _has_identity(data):
            logger.warning("Skipping unidentifiable schedule record: %r", raw_record)
            continue

        schedule = None
        matched_id = str(raw_record.get("matched_existing_id") or "").strip()
        if matched_id and matched_id != "NONE":
            try:
                candidate = by_id.get(int(matched_id))
            except ValueError:
                candidate = None
            if candidate is not None and candidate.id not in claimed:
                schedule = candidate
        if schedule is None:
            key = _record_identity(
                data["patient_name"], data["surgery_name"],
                data["date"], data["room"], data["time_slot"],
            )
            candidate = by_identity.get(key)
            if candidate is not None and candidate.id not in claimed:
                schedule = candidate

        if schedule:
            claimed.add(schedule.id)
            changed = any(getattr(schedule, field) != value for field, value in data.items())
            if changed:
                for field, value in data.items():
                    setattr(schedule, field, value)
                schedule.save()
        else:
            SurgerySchedule.objects.create(user=user, **data)


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
