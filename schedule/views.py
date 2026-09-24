from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import SurgerySchedule
from .forms import ScheduleUploadForm
from collections import defaultdict
from dateutil import parser as date_parser
import openpyxl
import os
import re
import subprocess
from io import BytesIO
from .models import SurgerySchedule, PatientMemo, ScheduleUploadJob, BoardNotice
from . import table_parser
from .ai_client import extract_schedules
from django.contrib import messages
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import threading
from difflib import SequenceMatcher
from django.db import transaction
from django.views.decorators.http import require_POST
from .gemini_client import ScheduleExtractionError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json
import logging
from accounts.decorators import user_is_specially_approved

logger = logging.getLogger(__name__)


def _get_build_version():
    """Short git commit hash of whatever's actually running, shown in a corner of the
    schedule dashboard. Purely a deploy-sanity-check: several rounds of "the fix still
    isn't working" turned out to be testing against a not-yet-deployed commit, so this
    lets that be confirmed by eye in the browser instead of by digging through logs."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


BUILD_VERSION = _get_build_version()

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
    "anesthesiologist": 50,
    "anesthesia_type": 20,
    "patient_name": 50,
    "patient_info": 20,
    "status": 50,
}


# Free-text status values (whatever the uploaded file / Gemini used) -> board group.
ONGOING_STATUSES = {"진행중", "수술중", "마취중", "입실", "진행"}
FINISHED_STATUSES = {"완료", "종료", "수술완료", "퇴실", "회복", "회복실"}


def status_group(status):
    """'ongoing' | 'finished' | 'pending' for the dashboard board colors/counts."""
    status = _normalize_text(status)
    if status in ONGOING_STATUSES:
        return "ongoing"
    if status in FINISHED_STATUSES:
        return "finished"
    return "pending"


def _room_sort_key(room):
    """Natural order: 101, 102, ..., 110, 201, then P1, P2, ..., P10; blank rooms last."""
    room = _normalize_text(room)
    parts = re.split(r"(\d+)", room)
    return (room == "", [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts if p])


# 현황판에서 수동으로 지정하는 상태값
MANUAL_STATUS = {"ongoing": "진행중", "finished": "완료", "pending": "예정"}


def build_board(schedules, memos=None):
    """Schedules -> JSON-able board data: rooms (naturally sorted, each with its cases and
    the case to feature on the room's row) plus overall counts.
    memos: {schedule_id: memo text}."""
    memos = memos or {}
    rooms = defaultdict(list)
    for schedule in schedules:
        rooms[schedule.room].append(schedule)

    board_rooms = []
    counts = {"ongoing": 0, "pending": 0, "finished": 0, "on_call": 0, "hold": 0}
    anesthesia_counts = {}
    for room in sorted(rooms, key=_room_sort_key):
        cases = []
        for s in rooms[room]:
            group = status_group(s.status)
            counts[group] += 1
            cases.append({
                "id": s.id,
                "date": s.date.isoformat(),
                "time_slot": s.time_slot,
                "surgery_name": s.surgery_name,
                "department": s.department,
                "surgeon": s.surgeon,
                "anesthesiologist": s.anesthesiologist,
                "anesthesia_type": s.anesthesia_type,
                "duration": s.duration,
                "patient_name": s.patient_name,
                "patient_info": s.patient_info,
                "status": s.status,
                "group": group,
                "status_locked": s.status_locked,
                "on_call": s.on_call,
                "hold": s.hold,
                "memo": memos.get(s.id, ""),
            })
            if group != "finished":
                counts["on_call"] += s.on_call
                counts["hold"] += s.hold
            if s.anesthesia_type:
                anesthesia_counts[s.anesthesia_type] = anesthesia_counts.get(s.anesthesia_type, 0) + 1
        groups = [c["group"] for c in cases]
        # 방 행에 보여줄 케이스: 진행 중 > 다음 예정 > 마지막 완료
        if "ongoing" in groups:
            current = groups.index("ongoing")
        elif "pending" in groups:
            current = groups.index("pending")
        else:
            current = len(cases) - 1
        board_rooms.append({
            "room": room,
            "state": cases[current]["group"],
            "current": current,
            "cases": cases,
        })

    total = counts["ongoing"] + counts["pending"] + counts["finished"]
    return {
        "rooms": board_rooms,
        "counts": counts,
        "total": total,
        "remaining": total - counts["finished"],
        "anesthesia_counts": anesthesia_counts,
        "dates": sorted({c["date"] for r in board_rooms for c in r["cases"]}),
    }


def _memo_map(user, schedule_ids=None):
    """{schedule_id: 메모} - 일정별 첫 메모 (handle_memo GET 과 같은 것), 내용이 있는 것만."""
    qs = PatientMemo.objects.filter(schedule__user=user)
    if schedule_ids is not None:
        qs = qs.filter(schedule_id__in=schedule_ids)
    memos = {}
    for schedule_id, content in qs.order_by("id").values_list("schedule_id", "content"):
        memos.setdefault(schedule_id, (content or "").strip())
    return {k: v for k, v in memos.items() if v}


def _room_schedules(user, room):
    return list(SurgerySchedule.objects.filter(user=user, room=room).order_by("date", "room", "time_slot", "id"))


def apply_manual_status(schedule, target):
    """현황판에서 수술 상태를 수동으로 변경하고, 같은 방의 다른 수술을 맞춰 조정.
    - 완료: 이 수술을 완료로 하고, 방에 진행 중인 수술이 없으면 바로 다음 예정 수술을
      진행중으로 (다음 수술이 Hold 면 자동 시작하지 않음)
    - 진행중: 같은 방에서 진행 중이던 다른 수술은 예정으로 되돌림
    - 예정: 이 수술만 예정으로
    수동으로 바꾼 수술은 status_locked 로 표시해 이후 업데이트 파일이 덮어쓰지 않게 함."""
    room_cases = _room_schedules(schedule.user, schedule.room)
    changed = []

    def set_status(case, value):
        if case.status != value or not case.status_locked:
            case.status, case.status_locked = value, True
            changed.append(case)

    if target == "ongoing":
        for case in room_cases:
            if case.id != schedule.id and status_group(case.status) == "ongoing":
                set_status(case, MANUAL_STATUS["pending"])
        set_status(schedule, MANUAL_STATUS["ongoing"])
    elif target == "finished":
        set_status(schedule, MANUAL_STATUS["finished"])
        others_ongoing = any(
            c.id != schedule.id and status_group(c.status) == "ongoing" for c in room_cases)
        if not others_ongoing:
            index = next(i for i, c in enumerate(room_cases) if c.id == schedule.id)
            nxt = next((c for c in room_cases[index + 1:] if status_group(c.status) == "pending"), None)
            if nxt is not None and not nxt.hold:
                set_status(nxt, MANUAL_STATUS["ongoing"])
    else:
        set_status(schedule, MANUAL_STATUS["pending"])

    for case in changed:
        case.save(update_fields=["status", "status_locked"])
    return changed


@login_required
@user_is_specially_approved
def schedule_dashboard(request):
    form = ScheduleUploadForm()
    error_message = None
    schedules = SurgerySchedule.objects.filter(user=request.user).order_by("date", "room", "time_slot", "id")
    board = build_board(schedules, _memo_map(request.user))

    if request.method == "POST":
        # 'update'(기본) 또는 'replace' - 값이 빠져도 기존 일정·메모를 지우지 않도록 update 가 기본
        action = 'replace' if request.POST.get('action') == 'replace' else 'update'
        form = ScheduleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            try:
                records, source_text = read_upload(uploaded_file)
                if records is not None:
                    # 표 형식 파일: AI 없이 바로 반영
                    count = apply_records(records, request.user, action)
                    messages.success(request, f"'{uploaded_file.name}' 에서 {count}건을 표 형식으로 읽어 반영했습니다.")
                    return redirect("schedule_dashboard")
                # 자유 형식 파일: AI 분석은 오래 걸릴 수 있어 백그라운드 작업으로 처리
                job = ScheduleUploadJob.objects.create(user=request.user, filename=uploaded_file.name[:255], action=action)
                start_background(run_upload_job, job.id, source_text)
                return redirect(f"{reverse('schedule_dashboard')}?job={job.id}")
            except (ScheduleExtractionError, ValueError) as exc:
                error_message = str(exc)
            except Exception:
                logger.exception("Schedule upload failed for user=%s", request.user)
                error_message = "일정을 처리하는 중 예기치 못한 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    job = None
    job_id = request.GET.get("job", "")
    if job_id.isdigit():
        job = ScheduleUploadJob.objects.filter(id=int(job_id), user=request.user).first()

    return render(request, "schedule/dashboard.html", {
        "board": board,
        "form": form,
        "error_message": error_message,
        "build_version": BUILD_VERSION,
        "job": job,
        "notice": BoardNotice.objects.filter(user=request.user).first(),
    })


def _decode_text(raw):
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일의 텍스트 인코딩을 해석할 수 없습니다.")


def read_upload(uploaded_file):
    """-> (records, source_text). records is set when the file is a table table_parser could
    read by column name (no AI needed); otherwise None and source_text is the plain-text
    dump for AI extraction."""
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()
    today = timezone.localdate()

    if name.endswith((".xlsx", ".xls")):
        try:
            workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True)
        except Exception as exc:
            raise ValueError("엑셀 파일을 읽을 수 없습니다. .xls(구형 엑셀)라면 .xlsx 로 다시 저장해서 올려주세요.") from exc
        records = table_parser.parse_workbook(workbook, uploaded_file.name, today)
        if records:
            return records, ""
        lines = []
        for sheet in workbook.worksheets:
            lines.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if cell is None else str(cell) for cell in row]
                if any(cell.strip() for cell in cells):
                    lines.append("\t".join(cells))
        return None, "\n".join(lines)

    text = _decode_text(raw)
    records = table_parser.parse_delimited_text(text, uploaded_file.name, today)
    return (records, "") if records else (None, text)


def extract_text_from_upload(uploaded_file):
    """Plain-text dump of an upload (kept for callers that always want AI extraction)."""
    return read_upload(uploaded_file)[1]


def apply_records(records, user, action):
    """Saves extracted records for user (replace = wipe first; update = match and keep memos)."""
    records = [r for r in records if isinstance(r, dict)]
    if not records:
        raise ScheduleExtractionError("파일에서 수술 일정을 찾지 못했습니다.")
    with transaction.atomic():
        if action == 'replace':
            SurgerySchedule.objects.filter(user=user).delete()
            create_schedules_from_records(records, user)
        else:
            update_schedules_from_records(records, user, list(SurgerySchedule.objects.filter(user=user)))
    return len(records)


def start_background(func, *args):
    """Runs func(*args) in a daemon thread and closes that thread's DB connection after."""
    def target():
        try:
            func(*args)
        finally:
            connection.close()
    threading.Thread(target=target, daemon=True).start()


def run_upload_job(job_id, source_text):
    job = ScheduleUploadJob.objects.select_related("user").get(id=job_id)
    try:
        records = extract_schedules(source_text, job.filename)
        count = apply_records(records, job.user, job.action)
        job.status, job.message = "done", f"'{job.filename}' 에서 {count}건을 AI로 읽어 반영했습니다."
    except (ScheduleExtractionError, ValueError) as exc:
        job.status, job.message = "error", str(exc)
    except Exception:
        logger.exception("Schedule upload job %s failed", job_id)
        job.status, job.message = "error", "일정을 처리하는 중 예기치 못한 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    job.save(update_fields=["status", "message", "updated_at"])


# 이보다 오래 '처리 중'이면 서버 재시작 등으로 작업이 끊긴 것으로 봄
STALE_JOB_AFTER = timedelta(minutes=8)


@login_required
@user_is_specially_approved
def upload_job_status(request, job_id):
    job = ScheduleUploadJob.objects.filter(id=job_id, user=request.user).first()
    if job is None:
        return JsonResponse({"status": "error", "message": "Job not found"}, status=404)
    if job.status == "running" and timezone.now() - job.updated_at > STALE_JOB_AFTER:
        job.status, job.message = "error", "처리가 중단되었습니다 (서버 재시작 등). 다시 업로드해주세요."
        job.save(update_fields=["status", "message", "updated_at"])
    return JsonResponse({"status": "success", "job": {"id": job.id, "state": job.status, "message": job.message,
                                                      "filename": job.filename}})


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
        "anesthesiologist": str(record.get("anesthesiologist") or "").strip(),
        "anesthesia_type": table_parser.normalize_anesthesia(record.get("anesthesia_type")),
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
        if not isinstance(raw_record, dict):
            continue
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


def _op_similarity(a, b):
    """0..1 similarity of two surgery names, ignoring case, spacing and punctuation
    (so "TKRA (Rt)" ~ "TKRA Rt" but is clearly closer to it than to "TKRA (Lt)")."""
    def norm(value):
        return re.sub(r"[^0-9a-z가-힣]+", " ", (value or "").lower()).strip()
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _match_score(data, schedule):
    """How likely an uploaded record and an existing row are the same case, or None if they
    can't be (different patient). Same registration number or same patient name is required;
    two different registration numbers always mean two different patients, even with the
    same name. Among one patient's several cases, surgery name similarity (then surgeon,
    then an exact case key) decides which old case - and memo - a new record inherits."""
    new_reg = _registration_number(data["patient_info"])
    old_reg = _registration_number(schedule.patient_info)
    same_reg = bool(new_reg and old_reg and new_reg == old_reg)
    if new_reg and old_reg and not same_reg:
        return None
    same_name = bool(data["patient_name"]) and _normalize_text(data["patient_name"]) == _normalize_text(schedule.patient_name)
    if not (same_reg or same_name):
        return None
    score = (100 if same_reg else 0) + (50 if same_name else 0)
    score += 20 * _op_similarity(data["surgery_name"], schedule.surgery_name)
    if _normalize_text(data["surgeon"]) and _normalize_text(data["surgeon"]) == _normalize_text(schedule.surgeon):
        score += 5
    if _case_key(data["patient_name"], data["surgery_name"], data["surgeon"]) == _case_key(
            schedule.patient_name, schedule.surgery_name, schedule.surgeon):
        score += 10
    return score


def update_schedules_from_records(records, user, existing_schedules):
    """Gemini-extracted records -> synced SurgerySchedule rows for `user`.

    Every new record is paired with at most one existing row, so the row (same pk) and
    therefore its memo carry over even if room, time, order, status or the wording of the
    surgery name/surgeon changed:
      1. Candidate pairs need the same registration number (_registration_number) or the
         same patient name, and never two *different* registration numbers.
      2. Pairs are scored (_match_score) and assigned best-first across the whole upload,
         not record by record - so when one patient has several cases, each new record
         goes to the old case with the most similar surgery name instead of whichever old
         case happened to come first (which used to swap memos between the cases).
      3. Records with no patient name at all fall back to (date, room, time_slot).
    A matched row is updated in place; a manually entered anesthesiologist is kept when
    the new file has none. A record with no match is inserted fresh (no memo yet). An
    existing row with no match in the new upload is treated as no longer part of the
    schedule and deleted - PatientMemo cascades, so its memo goes with it.
    """
    datas = []
    for raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        data = _normalize_record(raw_record)
        if not _has_identity(data):
            logger.warning("Skipping unidentifiable schedule record: %r", raw_record)
            continue
        datas.append(data)

    pairs = []
    for i, data in enumerate(datas):
        for schedule in existing_schedules:
            score = _match_score(data, schedule)
            if score is not None:
                pairs.append((score, i, schedule.id))
    # 점수 높은 쌍부터 배정 (동점이면 파일 순서 / 기존 id 순)
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))

    by_id = {schedule.id: schedule for schedule in existing_schedules}
    assigned = {}
    claimed_ids = set()
    for score, i, schedule_id in pairs:
        if i in assigned or schedule_id in claimed_ids:
            continue
        assigned[i] = by_id[schedule_id]
        claimed_ids.add(schedule_id)

    by_slot = {}
    for schedule in existing_schedules:
        if not schedule.patient_name:
            by_slot.setdefault(_slot_key(schedule.date, schedule.room, schedule.time_slot), schedule)
    for i, data in enumerate(datas):
        if i in assigned or data["patient_name"]:
            continue
        candidate = by_slot.get(_slot_key(data["date"], data["room"], data["time_slot"]))
        if candidate is not None and candidate.id not in claimed_ids:
            assigned[i] = candidate
            claimed_ids.add(candidate.id)

    created_count = 0
    for i, data in enumerate(datas):
        schedule = assigned.get(i)
        if schedule is None:
            created_count += 1
            SurgerySchedule.objects.create(user=user, **data)
            continue
        # 파일에 없으면 현황판에서 직접 입력한 값 유지
        for manual_field in ("anesthesiologist", "anesthesia_type"):
            if not data[manual_field]:
                data[manual_field] = getattr(schedule, manual_field)
        if schedule.status_locked:
            # 현황판에서 수동으로 바꾼 상태(완료/진행중 등)는 파일 상태로 되돌리지 않음
            data["status"] = schedule.status
        if any(getattr(schedule, field) != value for field, value in data.items()):
            for field, value in data.items():
                setattr(schedule, field, value)
            schedule.save()

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
        user, len(assigned), created_count, len(stale),
    )


@login_required
@user_is_specially_approved
@require_POST
def update_schedule(request, schedule_id):
    """현황판에서 수술 한 건을 수정: 마취의 입력, 당직/Hold 표시, 상태(진행중/완료/예정) 변경.
    응답으로 그 방의 최신 상태(build_board 의 room 항목)를 돌려줌."""
    schedule = SurgerySchedule.objects.filter(id=schedule_id, user=request.user).first()
    if schedule is None:
        return JsonResponse({"status": "error", "message": "Schedule not found"}, status=404)
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    if "status" in data and data["status"] not in MANUAL_STATUS:
        return JsonResponse({"status": "error", "message": "Invalid status"}, status=400)

    with transaction.atomic():
        fields = []
        if "anesthesiologist" in data:
            schedule.anesthesiologist = str(data.get("anesthesiologist") or "").strip()[:FIELD_MAX_LENGTHS["anesthesiologist"]]
            fields.append("anesthesiologist")
        if "anesthesia_type" in data:
            schedule.anesthesia_type = table_parser.normalize_anesthesia(data.get("anesthesia_type"))[:FIELD_MAX_LENGTHS["anesthesia_type"]]
            fields.append("anesthesia_type")
        for flag in ("on_call", "hold"):
            if flag in data:
                setattr(schedule, flag, bool(data[flag]))
                fields.append(flag)
        if fields:
            schedule.save(update_fields=fields)
        if "status" in data:
            apply_manual_status(schedule, data["status"])

    room_cases = _room_schedules(request.user, schedule.room)
    board = build_board(room_cases, _memo_map(request.user, [c.id for c in room_cases]))
    return JsonResponse({"status": "success", "room": board["rooms"][0]})


@login_required
@user_is_specially_approved
@require_POST
def save_notice(request):
    """현황판 공지·메모 칸 저장 (자동 저장)."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    content = str((data or {}).get("content") or "")[:20000]
    notice, _ = BoardNotice.objects.update_or_create(user=request.user, defaults={"content": content})
    return JsonResponse({"status": "success", "updated_at": timezone.localtime(notice.updated_at).strftime("%H:%M")})


@login_required
@user_is_specially_approved
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def handle_memo(request, schedule_id):
    try:
        # 본인 일정의 메모만 읽고 쓸 수 있음
        schedule = SurgerySchedule.objects.get(id=schedule_id, user=request.user)
    except SurgerySchedule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)

    if request.method == "GET":
        memo = PatientMemo.objects.filter(schedule=schedule).order_by("id").first()
        return JsonResponse({
            'status': 'success',
            'content': memo.content if memo else ''
        })

    elif request.method == "POST":
        try:
            data = json.loads(request.body)
            content = data.get('content', '')

            memo = PatientMemo.objects.filter(schedule=schedule).order_by("id").first()
            if memo is None:
                PatientMemo.objects.create(schedule=schedule, content=content)
            else:
                memo.content = content
                memo.save(update_fields=["content", "updated_at"])

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
