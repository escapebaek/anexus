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
from .models import SurgerySchedule, PatientMemo, ScheduleUploadJob, BoardNotice, DutyStaff, RoomKeeper, SavedStaff, RosterSeed
from . import table_parser
from .ai_client import extract_schedules, find_duration_column
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
import hashlib
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
        for s in sorted(rooms[room], key=case_order_key):
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
                "started_at": timezone.localtime(s.started_at).isoformat() if s.started_at else None,
                "patient_name": s.patient_name,
                "patient_info": s.patient_info,
                "status": s.status,
                "group": group,
                "status_locked": s.status_locked,
                "on_call": s.on_call,
                "hold": s.hold,
                "memo": memos.get(s.id, ""),
                "manual": s.manual,
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


def case_order_key(schedule):
    """방 안 순서: 날짜 → 현황판에서 직접 정한 순서(position) → 시간 → 등록 순.
    순서를 정하지 않은 수술(position=0)은 직접 정한 수술들 뒤에 시간 순으로 옴."""
    return (schedule.date, schedule.position or 10 ** 9, schedule.time_slot, schedule.id)


def _room_schedules(user, room):
    return sorted(SurgerySchedule.objects.filter(user=user, room=room), key=case_order_key)


def move_case_in_room(schedule, direction):
    """방 안에서 한 칸 앞/뒤로. 그 방 수술 전체에 1..n 순서를 매겨 저장."""
    cases = _room_schedules(schedule.user, schedule.room)
    index = next(i for i, c in enumerate(cases) if c.id == schedule.id)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(cases):
        cases[index], cases[target] = cases[target], cases[index]
    for position, case in enumerate(cases, start=1):
        if case.position != position:
            case.position = position
            case.save(update_fields=["position"])


def move_case_to_room(schedule, room):
    """다른 방으로 옮김 (그 방의 순서 지정 수술들 뒤, 나머지와는 시간 순).
    다음 스케줄 업데이트 때는 파일의 방·순서로 다시 맞춰짐."""
    schedule.room, schedule.position = room, 0
    schedule.save(update_fields=["room", "position"])


def place_case(schedule, room, index):
    """현황판 '순서 변경'에서 끌어다 놓기: room 의 index 번째 자리로 (방이 같으면 순서만, 다르면 방도 이동).
    그 방 수술 전체에 1..n 순서를 매겨 저장. 다음 스케줄 업데이트 때는 파일의 방·순서로 다시 맞춰짐."""
    cases = [c for c in _room_schedules(schedule.user, room) if c.id != schedule.id]
    index = max(0, min(int(index), len(cases)))
    schedule.room = room
    cases.insert(index, schedule)
    for position, case in enumerate(cases, start=1):
        if case.position != position or case is schedule:
            case.position = position
            case.save(update_fields=["room", "position"])


def _now():
    return timezone.now()


def apply_manual_status(schedule, target):
    """현황판에서 수술 상태를 수동으로 변경하고, 같은 방의 다른 수술을 맞춰 조정.
    - 완료: 이 수술을 완료로 하고, 방에 진행 중인 수술이 없으면 바로 다음 예정 수술을
      진행중으로 (다음 수술이 Hold 면 자동 시작하지 않음)
    - 진행중: 같은 방에서 진행 중이던 다른 수술은 예정으로 되돌림
    - 예정: 이 수술만 예정으로
    수동으로 바꾼 수술은 status_locked 로 표시해 이후 업데이트 파일이 덮어쓰지 않게 함.
    진행중이 되는 순간을 started_at 으로 기록 (종료 예정 = started_at + duration), 완료 시각은 finished_at."""
    room_cases = _room_schedules(schedule.user, schedule.room)
    changed = []
    now = _now()

    def set_status(case, value):
        was = status_group(case.status)
        if case.status != value or not case.status_locked:
            case.status, case.status_locked = value, True
            changed.append(case)
        group = status_group(value)
        if group == was and not (group == "ongoing" and case.started_at is None):
            return
        if group == "ongoing":
            case.started_at, case.finished_at = now, None
        elif group == "finished":
            case.finished_at = now
        else:
            case.started_at = case.finished_at = None
        if case not in changed:
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
        case.save(update_fields=["status", "status_locked", "started_at", "finished_at"])
    return changed


MAX_DURATION_MINUTES = 24 * 60


def parse_start_time(value, now=None):
    """현황판에서 입력한 시작 시각 'HH:MM' -> 오늘 그 시각 (현지 시간). 지금보다 늦으면
    자정 전에 시작한 수술로 보고 전날. 빈 값은 None, 형식이 틀리면 ValueError."""
    text = str(value or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError("시작 시각은 13:05 처럼 24시간 형식으로 입력하세요.")
    now = timezone.localtime(now or _now())
    started = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    if started > now + timedelta(minutes=1):
        started -= timedelta(days=1)
    return started


def normalize_time_slot(value):
    """현황판에서 입력한 예정 시각. 930 / 9:30 / 9.30 -> 09:30 (방 안에서 시간 순 정렬이 맞도록).
    8A, TF1 처럼 병원 고유 표기는 그대로 둠."""
    text = re.sub(r"\s+", "", str(value or ""))
    match = re.fullmatch(r"(\d{1,2})[:.;]?(\d{2})", text)
    if match and int(match.group(1)) <= 23 and int(match.group(2)) <= 59:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    return text[:FIELD_MAX_LENGTHS["time_slot"]]


@login_required
@user_is_specially_approved
def schedule_dashboard(request):
    form = ScheduleUploadForm()
    error_message = None
    schedules = SurgerySchedule.objects.filter(user=request.user)
    board = build_board(schedules, _memo_map(request.user))

    if request.method == "POST":
        # 'update'(기본) 또는 'replace' - 값이 빠져도 기존 일정·메모를 지우지 않도록 update 가 기본
        action = 'replace' if request.POST.get('action') == 'replace' else 'update'
        form = ScheduleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            try:
                # 표 형식은 규칙으로 바로 읽음 (헷갈리는 예상 시간 열만 AI 에 짧게 물어봄).
                # 표로 읽을 수 없는 파일만 AI 분석으로 넘김.
                records, source_text, report = read_upload(uploaded_file)
                if records is not None:
                    # 표 형식 파일: AI 없이 바로 반영
                    count = apply_records(records, request.user, action)
                    messages.success(request, _table_message(uploaded_file.name, count, report, records))
                    return redirect("schedule_dashboard")
                # 자유 형식 파일: AI 분석은 오래 걸릴 수 있어 백그라운드 작업으로 처리
                job = ScheduleUploadJob.objects.create(
                    user=request.user, filename=uploaded_file.name[:255], action=action,
                    message=report.get("reason") or "")
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
        if job is not None:
            job.reason, job.progress = split_progress(job.message)

    return render(request, "schedule/dashboard.html", {
        "board": board,
        "staff": staff_state(request.user, board_date(board)),
        "form": form,
        "error_message": error_message,
        "build_version": BUILD_VERSION,
        "job": job,
        "notice": BoardNotice.objects.filter(user=request.user).first(),
        "trash_count": len(trash_list(request.user)),   # 24시간 지난 것은 정리한 뒤 셈
    })


def _decode_text(raw):
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일의 텍스트 인코딩을 해석할 수 없습니다.")


def _table_message(filename, count, report, records=()):
    used = ", ".join(report.get("used") or [])
    unused = ", ".join(report.get("unused") or [])
    message = f"'{filename}' 에서 {count}건을 표 형식으로 읽어 반영했습니다. 읽은 열: {used}."
    if unused:
        message += f" 사용하지 않은 열: {unused}."
    if records and not any(r.get("duration") for r in records):
        message += " 예상 수술 시간 열이 없어, 종료 예정 시각을 보려면 수술 메뉴에서 예상 시간을 입력하세요."
    return message


def read_upload(uploaded_file, use_table=True):
    """-> (records, source_text, report). records is set when the file is a table
    table_parser could read by column name (no AI needed); otherwise None and
    source_text is the plain-text dump for AI extraction. report says which columns
    were used / ignored, or why the file wasn't read as a table."""
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()
    today = timezone.localdate()
    report = {}

    if name.endswith((".xlsx", ".xls")):
        try:
            workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True)
        except Exception as exc:
            raise ValueError("엑셀 파일을 읽을 수 없습니다. .xls(구형 엑셀)라면 .xlsx 로 다시 저장해서 올려주세요.") from exc
        records = table_parser.parse_workbook(workbook, uploaded_file.name, today, report,
                                              find_duration_column) if use_table else None
        if records:
            return records, "", report
        lines = []
        for sheet in workbook.worksheets:
            lines.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if cell is None else str(cell) for cell in row]
                if any(cell.strip() for cell in cells):
                    lines.append("\t".join(cells))
        return None, "\n".join(lines), report

    text = _decode_text(raw)
    records = table_parser.parse_delimited_text(text, uploaded_file.name, today, report,
                                                find_duration_column) if use_table else None
    return (records, "", report) if records else (None, text, report)


def extract_text_from_upload(uploaded_file):
    """Plain-text dump of an upload (kept for callers that always want AI extraction)."""
    return read_upload(uploaded_file, use_table=False)[1]


def apply_records(records, user, action):
    """Saves extracted records for user (replace = wipe first; update = match and keep memos)."""
    records = [r for r in records if isinstance(r, dict)]
    if not records:
        raise ScheduleExtractionError("파일에서 수술 일정을 찾지 못했습니다.")
    with transaction.atomic():
        if action == 'replace':
            SurgerySchedule.all_objects.filter(user=user).delete()   # 전체 교체: 휴지통까지 비움
            create_schedules_from_records(records, user)
        else:
            # 휴지통의 수술도 함께 맞춰 봄: 파일에 다시 나와도 일부러 지운 수술은 지운 채로 둠
            update_schedules_from_records(records, user, list(SurgerySchedule.all_objects.filter(user=user)))
    return len(records)


def start_background(func, *args):
    """Runs func(*args) in a daemon thread and closes that thread's DB connection after."""
    def target():
        try:
            func(*args)
        finally:
            connection.close()
    threading.Thread(target=target, daemon=True).start()


PROGRESS_MARK = "\n[진행] "


def split_progress(message):
    """job.message = '표로 읽지 않은 이유' + (처리 중이면) 진행 표시. -> (이유, 진행)"""
    reason, _, progress = (message or "").partition(PROGRESS_MARK)
    return reason, progress


def run_upload_job(job_id, source_text):
    job = ScheduleUploadJob.objects.select_related("user").get(id=job_id)
    reason = job.message

    def progress(index, total):
        # updated_at 도 갱신해 오래 걸려도 '중단됨'으로 보지 않게 함
        ScheduleUploadJob.objects.filter(id=job_id).update(
            message=f"{reason}{PROGRESS_MARK}{total}조각 중 {index + 1}번째 분석 중", updated_at=timezone.now())

    try:
        records = extract_schedules(source_text, job.filename, progress)
        count = apply_records(records, job.user, job.action)
        job.status, job.message = "done", f"'{job.filename}' 에서 {count}건을 AI로 읽어 반영했습니다."
    except (ScheduleExtractionError, ValueError) as exc:
        job.status, job.message = "error", str(exc)
    except Exception:
        logger.exception("Schedule upload job %s failed", job_id)
        job.status, job.message = "error", "일정을 처리하는 중 예기치 못한 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    job.save(update_fields=["status", "message", "updated_at"])


# 이보다 오래 '처리 중'(진행 표시 갱신 없음)이면 서버 재시작 등으로 작업이 끊긴 것으로 봄.
# 로컬 AI 요청 하나가 최대 LOCALAI_TIMEOUT(기본 10분) 걸릴 수 있어 그보다 길게.
STALE_JOB_AFTER = timedelta(minutes=12)


@login_required
@user_is_specially_approved
def upload_job_status(request, job_id):
    job = ScheduleUploadJob.objects.filter(id=job_id, user=request.user).first()
    if job is None:
        return JsonResponse({"status": "error", "message": "Job not found"}, status=404)
    if job.status == "running" and timezone.now() - job.updated_at > STALE_JOB_AFTER:
        job.status, job.message = "error", "처리가 중단되었습니다 (서버 재시작 등). 다시 업로드해주세요."
        job.save(update_fields=["status", "message", "updated_at"])
    reason, progress = split_progress(job.message)
    return JsonResponse({"status": "success", "job": {"id": job.id, "state": job.status,
                                                      "message": reason if job.status == "running" else job.message,
                                                      "progress": progress if job.status == "running" else "",
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
        # 마취의는 업로드 파일에서 가져오지 않음 - 현황판에서 직접 입력/끌어다 놓기 (업데이트 때도 기존 값 유지)
        "anesthesiologist": "",
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
                pairs.append((schedule.deleted_at is not None, score, i, schedule.id))
    # 현황판에 있는 수술부터, 점수 높은 쌍부터 배정 (동점이면 파일 순서 / 기존 id 순).
    # 휴지통의 수술은 남은 줄하고만 짝지음 - 같은 환자의 살아 있는 수술이 휴지통 쪽에 밀려 지워지지 않게
    pairs.sort(key=lambda p: (p[0], -p[1], p[2], p[3]))
    pairs = [(score, i, schedule_id) for _, score, i, schedule_id in pairs]

    by_id = {schedule.id: schedule for schedule in existing_schedules}
    assigned = {}
    claimed_ids = set()
    for score, i, schedule_id in pairs:
        if i in assigned or schedule_id in claimed_ids:
            continue
        assigned[i] = by_id[schedule_id]
        claimed_ids.add(schedule_id)

    by_slot = {}
    for schedule in sorted(existing_schedules, key=lambda c: c.deleted_at is not None):  # 살아 있는 수술 먼저
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
        for manual_field in ("anesthesiologist", "anesthesia_type", "duration"):
            if not data[manual_field]:
                data[manual_field] = getattr(schedule, manual_field)
        if schedule.status_locked:
            # 현황판에서 수동으로 바꾼 상태(완료/진행중 등)는 파일 상태로 되돌리지 않음
            data["status"] = schedule.status
        data["manual"] = False  # 직접 추가했던 수술도 파일에 나오면 이제 파일 기준
        if any(getattr(schedule, field) != value for field, value in data.items()):
            for field, value in data.items():
                setattr(schedule, field, value)
            schedule.save()

    # 방·순서는 업로드한 파일이 기준: 현황판에서 직접 옮기거나 정렬한 순서는 여기서 초기화
    SurgerySchedule.all_objects.filter(user=user).exclude(position=0).update(position=0)

    # Whatever wasn't claimed wasn't matched by anything in this upload - the case is no
    # longer part of the schedule, so remove it (and its memo along with it).
    # (현황판에서 직접 추가한 수술은 파일에 없어도 유지, 휴지통의 수술은 휴지통에 그대로)
    stale = [schedule for schedule in existing_schedules
             if schedule.id not in claimed_ids and not schedule.manual and schedule.deleted_at is None]
    if stale:
        logger.warning(
            "update_schedules_from_records: deleting %d unmatched schedule(s) for user=%s: %s",
            len(stale), user,
            [(s.id, s.patient_name, s.surgery_name, s.surgeon, s.patient_info) for s in stale],
        )
        SurgerySchedule.all_objects.filter(id__in=[schedule.id for schedule in stale]).delete()

    logger.info(
        "update_schedules_from_records: user=%s matched=%d created=%d deleted=%d",
        user, len(assigned), created_count, len(stale),
    )


@login_required
@user_is_specially_approved
@require_POST
def update_schedule(request, schedule_id):
    """현황판에서 수술 한 건을 수정: 마취의 입력, 당직/Hold 표시, 상태(진행중/완료/예정) 변경,
    예상 시간(분)·시작 시각(HH:MM)·예정 시각(time_slot)·수술명 수정.
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
    if data.get("delete"):
        # 휴지통으로 (메모 포함 그대로 보관) - '삭제된 수술'에서 복원
        schedule.deleted_at = timezone.now()
        schedule.save(update_fields=["deleted_at"])
        board = build_board(SurgerySchedule.objects.filter(user=request.user), _memo_map(request.user))
        return JsonResponse({"status": "success", "board": board, "trash": trash_list(request.user)})
    if "status" in data and data["status"] not in MANUAL_STATUS:
        return JsonResponse({"status": "error", "message": "Invalid status"}, status=400)
    if "move" in data and data["move"] not in ("up", "down"):
        return JsonResponse({"status": "error", "message": "Invalid move"}, status=400)
    place = None
    if "place" in data:
        raw = data.get("place") if isinstance(data.get("place"), dict) else {}
        place_room = re.sub(r"\s+", " ", str(raw.get("room") or "")).strip()[:FIELD_MAX_LENGTHS["room"]]
        try:
            place = (place_room, int(raw.get("index")))
        except (TypeError, ValueError):
            place = None
        if not place or not place_room:
            return JsonResponse({"status": "error", "message": "Invalid place"}, status=400)
    if "duration" in data:
        try:
            duration = int(data.get("duration") or 0)
        except (TypeError, ValueError):
            duration = -1
        if not 0 <= duration <= MAX_DURATION_MINUTES:
            return JsonResponse({"status": "error", "message": "예상 시간은 0~1440분으로 입력하세요."}, status=400)
    if "started_at" in data:
        try:
            started_at = parse_start_time(data.get("started_at"))
        except ValueError as exc:
            return JsonResponse({"status": "error", "message": str(exc)}, status=400)
    info = {}
    if "time_slot" in data:
        info["time_slot"] = normalize_time_slot(data.get("time_slot"))
    if "surgery_name" in data:
        info["surgery_name"] = re.sub(r"\s+", " ", str(data.get("surgery_name") or "")).strip()[:FIELD_MAX_LENGTHS["surgery_name"]]
        if not info["surgery_name"]:
            return JsonResponse({"status": "error", "message": "수술명을 입력하세요."}, status=400)
    new_room = None
    if "room" in data:
        new_room = re.sub(r"\s+", " ", str(data.get("room") or "")).strip()[:FIELD_MAX_LENGTHS["room"]]
        if not new_room:
            return JsonResponse({"status": "error", "message": "방 이름을 입력하세요."}, status=400)
    old_room = schedule.room

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
        if "duration" in data:
            schedule.duration = duration
            fields.append("duration")
        if "started_at" in data:
            schedule.started_at = started_at
            fields.append("started_at")
        for field, value in info.items():
            setattr(schedule, field, value)
            fields.append(field)
        if fields:
            schedule.save(update_fields=fields)
        if "on_call" in data:
            # 당직 표시는 그 방에서 이 수술 뒤로(끝나지 않은 수술) 모두 같이 켜고 끔
            cases = _room_schedules(request.user, schedule.room)
            index = next(i for i, c in enumerate(cases) if c.id == schedule.id)
            later = [c.id for c in cases[index + 1:] if status_group(c.status) != "finished"]
            SurgerySchedule.objects.filter(id__in=later).update(on_call=schedule.on_call)
        if "status" in data:
            apply_manual_status(schedule, data["status"])
        if "move" in data:
            move_case_in_room(schedule, data["move"])
        if new_room is not None and new_room != old_room:
            move_case_to_room(schedule, new_room)
        if place is not None:
            place_case(schedule, *place)

    if place is not None or (new_room is not None and new_room != old_room):
        # 방이 바뀌면 방 목록 자체가 달라질 수 있어 현황판 전체를 돌려줌
        board = build_board(SurgerySchedule.objects.filter(user=request.user), _memo_map(request.user))
        return JsonResponse({"status": "success", "board": board,
                             "room": next(r for r in board["rooms"] if r["room"] == schedule.room)})
    room_cases = _room_schedules(request.user, schedule.room)
    board = build_board(room_cases, _memo_map(request.user, [c.id for c in room_cases]))
    return JsonResponse({"status": "success", "room": board["rooms"][0]})


@login_required
@user_is_specially_approved
@require_POST
def create_schedule(request):
    """현황판에서 수술을 직접 추가. room·surgery_name 필수, 날짜는 현황판 날짜.
    파일로 '업데이트' 해도 지워지지 않음 (manual). 응답으로 현황판 전체를 돌려줌."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    clean = lambda key: re.sub(r"\s+", " ", str(data.get(key) or "")).strip()[:FIELD_MAX_LENGTHS[key]]
    room, surgery_name = clean("room"), clean("surgery_name")
    if not room or not surgery_name:
        return JsonResponse({"status": "error", "message": "방과 수술명을 입력하세요."}, status=400)
    try:
        duration = int(data.get("duration") or 0)
    except (TypeError, ValueError):
        duration = -1
    if not 0 <= duration <= MAX_DURATION_MINUTES:
        return JsonResponse({"status": "error", "message": "예상 시간은 0~1440분으로 입력하세요."}, status=400)
    user = request.user
    day = board_date(build_board(SurgerySchedule.objects.filter(user=user)))
    with transaction.atomic():
        schedule = SurgerySchedule.objects.create(
            user=user, date=day, room=room, time_slot=normalize_time_slot(data.get("time_slot")),
            surgery_name=surgery_name, department=clean("department"), surgeon=clean("surgeon"),
            anesthesia_type=table_parser.normalize_anesthesia(data.get("anesthesia_type"))[:FIELD_MAX_LENGTHS["anesthesia_type"]],
            duration=duration, patient_name=clean("patient_name"), patient_info=clean("patient_info"),
            status="예정", manual=True)
        # 같은 방에 직접 정한 순서가 있으면 맨 뒤에 붙임 (없으면 시간 순)
        if SurgerySchedule.objects.filter(user=user, room=room).exclude(position=0).exists():
            cases = [c for c in _room_schedules(user, room) if c.id != schedule.id] + [schedule]
            for position, case in enumerate(cases, start=1):
                if case.position != position:
                    case.position = position
                    case.save(update_fields=["position"])
    board = build_board(SurgerySchedule.objects.filter(user=user), _memo_map(user))
    return JsonResponse({"status": "success", "id": schedule.id, "board": board})


TRASH_KEEP = timedelta(hours=24)


def trash_list(user):
    """휴지통 목록 (최근 삭제 순). 삭제하고 24시간(TRASH_KEEP) 지난 것은 여기서 영구 삭제."""
    SurgerySchedule.all_objects.filter(user=user, deleted_at__lt=timezone.now() - TRASH_KEEP).delete()
    rows = SurgerySchedule.all_objects.filter(user=user, deleted_at__isnull=False).order_by("-deleted_at", "-id")
    return [{
        "id": s.id, "date": s.date.isoformat(), "room": s.room, "time_slot": s.time_slot,
        "surgery_name": s.surgery_name, "patient_name": s.patient_name, "surgeon": s.surgeon,
        "deleted_at": timezone.localtime(s.deleted_at).strftime("%m/%d %H:%M"),
    } for s in rows]


@login_required
@user_is_specially_approved
@require_http_methods(["GET", "POST"])
def schedule_trash(request):
    """삭제된 수술(휴지통). GET: 목록 / POST {action: restore|purge, id}: 복원 또는 영구 삭제.
    응답: {trash, board?}"""
    user = request.user
    if request.method == "GET":
        return JsonResponse({"status": "success", "trash": trash_list(user)})
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    data = data if isinstance(data, dict) else {}
    schedule = SurgerySchedule.all_objects.filter(user=user, id=data.get("id"), deleted_at__isnull=False).first()
    if schedule is None:
        return JsonResponse({"status": "error", "message": "삭제된 수술을 찾지 못했습니다."}, status=404)
    if data.get("action") == "restore":
        schedule.deleted_at = None
        schedule.save(update_fields=["deleted_at"])
    elif data.get("action") == "purge":
        schedule.delete()
    else:
        return JsonResponse({"status": "error", "message": "요청을 이해하지 못했습니다."}, status=400)
    board = build_board(SurgerySchedule.objects.filter(user=user), _memo_map(user))
    return JsonResponse({"status": "success", "trash": trash_list(user), "board": board})


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


@login_required
def ai_check(request):
    """관리자용 로컬 AI 연결 점검: /schedule/ai-check/ 를 브라우저로 열면 어디서 막히는지 보여줌.
    (주소 확인 → 모델 목록 → 짧은 테스트 질문 1개). API 키 값은 보여주지 않음."""
    import time as _time

    from . import ai_client

    if not request.user.is_staff:
        return JsonResponse({"error": "관리자만 볼 수 있습니다."}, status=403)
    from django.conf import settings

    name = "localai"
    result = {
        "providers": ai_client.configured_providers(),
        "LOCALAI_URL": settings.LOCALAI_URL or "(없음)",
        # 키 값 대신 길이와 지문만: AI 컴퓨터에서 echo -n '키' | sha256sum 앞 8자리와 비교
        "LOCALAI_API_KEY": (f"설정됨 (길이 {len(settings.LOCALAI_API_KEY)}, sha256 앞자리 "
                            f"{hashlib.sha256(settings.LOCALAI_API_KEY.encode()).hexdigest()[:8]})"
                            if settings.LOCALAI_API_KEY else "(없음)"),
        "키를 보내는 헤더": settings.LOCALAI_AUTH_HEADER or "Authorization: Bearer, X-API-Key, api-key",
        "LOCALAI_MODEL": settings.LOCALAI_MODEL or "(비어 있음 - 자동 선택)",
    }
    if name not in result["providers"]:
        result["결론"] = "LOCALAI_URL 과 LOCALAI_API_KEY 를 Render 환경변수에 넣어야 합니다."
        return JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})

    result["요청 주소"] = ai_client._base_url(name)
    models, reason = ai_client.list_models(name)
    result["1. 모델 목록"] = models if models else f"실패 - {reason}"
    model = settings.LOCALAI_MODEL.split(",")[0].strip() if settings.LOCALAI_MODEL else (models or [""])[0]
    if not model:
        result["결론"] = f"서버에 닿지 못했거나 모델 목록이 없습니다: {reason}"
        return JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})

    started = _time.monotonic()
    try:
        answer = ai_client._ask_openai_compatible_json(
            name, 'Respond with ONLY this JSON: {"ok": true}', "ping", min(60, settings.LOCALAI_TIMEOUT))
        result["2. 테스트 질문"] = {"모델": model, "답": answer[:200],
                                "걸린 시간(초)": round(_time.monotonic() - started, 1)}
        result["결론"] = "정상 - 로컬 AI 에 연결되어 답을 받았습니다."
    except Exception as exc:  # 점검 화면이므로 어떤 실패든 원인을 그대로 보여줌
        result["2. 테스트 질문"] = f"실패 - {exc}"
        result["결론"] = ("모델 목록까지는 됐지만 질문에 답하지 못했습니다." if models
                        else f"로컬 AI 에 연결하지 못했습니다: {exc}")
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})


# ---------------------------------------------------------------------------
# 근무자 명단 · 방킵 배정 (스케줄 파일에는 보통 없어서 현황판에서 직접)
# ---------------------------------------------------------------------------
MAX_STAFF = 60


def board_date(board):
    """방킵을 기록할 날짜: 현황판에 오늘 일정이 있으면 오늘, 아니면 현황판 일정의 첫 날짜, 없으면 오늘."""
    today = timezone.localdate()
    dates = board.get("dates") or []
    if today.isoformat() in dates or not dates:
        return today
    return date_parser.parse(dates[0]).date()


def _clean_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:50]


def _recent_roster(user, day, role):
    last = DutyStaff.objects.filter(user=user, role=role, date__lt=day).order_by("-date") \
        .values_list("date", flat=True).first()
    if not last:
        return None
    return {"date": last.isoformat(), "count": DutyStaff.objects.filter(user=user, role=role, date=last).count()}


def staff_state(user, day):
    """-> {date,
           roster: [{name, rooms}] (근무자), keepers: {room: [names]}, recent: {date, count} | None,
           anes: [names] (마취의 명단), anes_recent: {date, count} | None,
           marks: {keeper|anes: {name: {off, duty}}} (퇴근·당직 표시가 있는 사람만),
           saved: {keeper|anes: [names]} (고정 명단)}
    그날 처음 보는 명단이면 고정 명단을 먼저 채움. 마취의를 맡은 수술 수는 화면이 현황판 데이터로 셈."""
    _seed_saved(user, day)
    keepers = defaultdict(list)
    rooms_of = defaultdict(list)
    for keeper in RoomKeeper.objects.filter(user=user, date=day):
        keepers[keeper.room].append(keeper.name)
        rooms_of[keeper.name].append(keeper.room)
    people = DutyStaff.objects.filter(user=user, date=day)
    roster = [{"name": s.name, "rooms": sorted(rooms_of.get(s.name, []), key=_room_sort_key)}
              for s in people if s.role == "keeper"]
    anes = [s.name for s in people if s.role == "anes"]
    marks = {"keeper": {}, "anes": {}}
    for s in people:
        if s.off or s.duty:
            marks[s.role][s.name] = {"off": s.off, "duty": s.duty}
    return {"date": day.isoformat(), "roster": roster, "keepers": dict(keepers),
            "recent": None if roster else _recent_roster(user, day, "keeper"),
            "anes": anes, "anes_recent": None if anes else _recent_roster(user, day, "anes"),
            "marks": marks, "saved": _saved_names(user)}


def _saved_names(user):
    saved = {"keeper": [], "anes": []}
    for s in SavedStaff.objects.filter(user=user):
        saved[s.role].append(s.name)
    return saved


def _seed_saved(user, day):
    """그날(역할별) 처음 한 번만 고정 명단을 그날 명단에 넣음. 이후 '오늘만 빼기' 한 사람은 다시 넣지 않음."""
    for role in ("keeper", "anes"):
        _, created = RosterSeed.objects.get_or_create(user=user, date=day, role=role)
        if created:
            names = list(SavedStaff.objects.filter(user=user, role=role).values_list("name", flat=True))
            if names:
                _add_staff(user, day, names, role)


def _add_staff(user, day, names, role="keeper"):
    existing = set(DutyStaff.objects.filter(user=user, date=day, role=role).values_list("name", flat=True))
    order = len(existing)
    for name in names:
        if name and name not in existing and len(existing) < MAX_STAFF:
            DutyStaff.objects.create(user=user, date=day, role=role, name=name, order=order)
            existing.add(name)
            order += 1


@login_required
@user_is_specially_approved
@require_POST
def staff_api(request):
    """근무자·마취의 명단과 방킵 변경. action:
    add(names) · remove(name) · load_recent  - role: keeper(근무자, 기본) | anes(마취의)
    mark(name, off?: bool, duty?: "today" | "yesterday" | "") - 퇴근·당직 표시
    save(name) · unsave(name) · save_all - 고정 명단 (다음 날부터 자동으로 명단에 들어감).
    remove 는 그날 명단에서만 빼고 고정 명단은 그대로.
    assign(name, room) · unassign(name, room) - 방킵. 한 사람은 하루에 한 방만 (다른 방으로 배정하면 옮겨짐).
    (수술별 마취의 자체는 schedule_update 의 anesthesiologist 로 저장)
    응답으로 그날의 명단·배정 전체를 돌려줌."""
    try:
        data = json.loads(request.body or b"{}")
        day = date_parser.isoparse(str(data.get("date"))).date()
    except (json.JSONDecodeError, ValueError, TypeError, OverflowError):
        return JsonResponse({"status": "error", "message": "날짜를 확인할 수 없습니다."}, status=400)
    user, action = request.user, data.get("action")
    role = "anes" if data.get("role") == "anes" else "keeper"
    name = _clean_name(data.get("name"))
    room = re.sub(r"\s+", " ", str(data.get("room") or "")).strip()[:FIELD_MAX_LENGTHS["room"]]

    with transaction.atomic():
        if action == "add":
            raw = data.get("names") or []
            raw = raw if isinstance(raw, list) else re.split(r"[,\n]", str(raw))
            _add_staff(user, day, [_clean_name(n) for n in raw], role)
        elif action == "remove" and name:
            DutyStaff.objects.filter(user=user, date=day, role=role, name=name).delete()
            if role == "keeper":
                RoomKeeper.objects.filter(user=user, date=day, name=name).delete()
        elif action == "load_recent":
            last = _recent_roster(user, day, role)
            if last:
                names = DutyStaff.objects.filter(user=user, role=role, date=last["date"]).values_list("name", flat=True)
                _add_staff(user, day, list(names), role)
                # 바로 전날 명단이면 그날의 '오늘 당직' 은 오늘의 '어제 당직' 으로
                if date_parser.isoparse(last["date"]).date() == day - timedelta(days=1):
                    on_call = DutyStaff.objects.filter(user=user, role=role, date=last["date"], duty="today") \
                        .values_list("name", flat=True)
                    DutyStaff.objects.filter(user=user, role=role, date=day, name__in=list(on_call), duty="") \
                        .update(duty="yesterday")
        elif action == "assign" and name and room:
            _add_staff(user, day, [name])
            RoomKeeper.objects.filter(user=user, date=day, name=name).exclude(room=room).delete()
            RoomKeeper.objects.get_or_create(user=user, date=day, room=room, name=name)
        elif action == "save" and name:
            _add_staff(user, day, [name], role)
            if len(_saved_names(user)[role]) < MAX_STAFF:
                order = SavedStaff.objects.filter(user=user, role=role).count()
                SavedStaff.objects.get_or_create(user=user, role=role, name=name, defaults={"order": order})
        elif action == "unsave" and name:
            SavedStaff.objects.filter(user=user, role=role, name=name).delete()
        elif action == "save_all":
            saved = set(_saved_names(user)[role])
            for person in DutyStaff.objects.filter(user=user, date=day, role=role):
                if person.name not in saved and len(saved) < MAX_STAFF:
                    SavedStaff.objects.create(user=user, role=role, name=person.name, order=len(saved))
                    saved.add(person.name)
        elif action == "mark" and name:
            fields = {}
            if "off" in data:
                fields["off"] = bool(data.get("off"))
            if "duty" in data:
                fields["duty"] = data.get("duty") if data.get("duty") in ("today", "yesterday") else ""
            if not fields:
                return JsonResponse({"status": "error", "message": "요청을 이해하지 못했습니다."}, status=400)
            DutyStaff.objects.filter(user=user, date=day, role=role, name=name).update(**fields)
        elif action == "unassign" and name and room:
            RoomKeeper.objects.filter(user=user, date=day, room=room, name=name).delete()
        else:
            return JsonResponse({"status": "error", "message": "요청을 이해하지 못했습니다."}, status=400)
    return JsonResponse({"status": "success", "staff": staff_state(user, day)})
