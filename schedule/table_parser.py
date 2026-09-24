"""Rule-based reader for schedule spreadsheets that have a header row.

Most institution exports (and schedule/surgery_schedule_template.xlsx) are plain
tables: one header row (날짜 / 방 / 시간 / 수술명 / 집도의 / 환자명 ...) followed by
one row per case. Those don't need an LLM at all - reading them by column name is
instant, free, and gives the same result every time (which also keeps "update"
matching stable, since names/surgery names come through verbatim).

parse_table_rows() returns None when it can't confidently recognize a header, so
the caller can fall back to AI extraction for free-form files (memos etc.).
"""
import csv
import io
import re
from datetime import date, datetime

from dateutil import parser as date_parser

# normalized header text -> field. Normalization: lowercase, no spaces/punctuation.
HEADER_SYNONYMS = {
    "date": ["날짜", "수술일", "수술일자", "일자", "수술날짜", "date", "opdate"],
    "room": ["방", "수술방", "수술실", "룸", "방번호", "room", "or", "orroom", "theater"],
    "time_slot": ["시간", "시작시간", "시작", "예정시간", "수술시작", "입실시간", "순서", "time", "start", "starttime"],
    "duration": ["수술시간", "소요시간", "예상시간", "예상소요시간", "수술소요시간", "duration", "optime"],
    "surgery_name": ["수술명", "수술", "술식", "수술명칭", "procedure", "operation", "surgery", "opname"],
    "department": ["진료과", "과", "진료과목", "dept", "department"],
    "surgeon": ["집도의", "집도", "주치의", "수술의", "surgeon"],
    "anesthesiologist": ["마취의", "마취과", "마취", "마취담당", "마취담당의", "마취과의사", "담당마취의", "anesthesiologist", "anesthesia"],
    "patient_name": ["환자명", "이름", "성명", "환자", "환자이름", "patient", "patientname", "name"],
    "regnum": ["등록번호", "병록번호", "차트번호", "환자번호", "mrn", "chartno", "id"],
    "age_sex": ["성별나이", "나이성별", "성나이", "나이", "성별", "age", "sex", "agesex", "sexage"],
    "patient_info": ["환자정보", "정보", "patientinfo"],
    "status": ["진행상황", "진행상태", "상태", "현황", "진행", "status"],
}
_SYNONYM_TO_FIELD = {syn: field for field, syns in HEADER_SYNONYMS.items() for syn in syns}

STATUS_MAP = {
    "대기": "예정", "예정": "예정", "대기중": "예정", "입실대기": "예정",
    "수술중": "진행중", "진행중": "진행중", "진행": "진행중", "마취중": "진행중", "입실": "진행중",
    "완료": "완료", "종료": "완료", "수술완료": "완료", "퇴실": "완료", "회복": "완료", "회복실": "완료",
}

HEADER_SEARCH_ROWS = 15


def _norm_header(value):
    return re.sub(r"[\s/()\[\]._\-·:]+", "", str(value or "")).lower()


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _map_header(row):
    """{field: column index} for a candidate header row (first column wins per field)."""
    mapping = {}
    for index, cell in enumerate(row):
        field = _SYNONYM_TO_FIELD.get(_norm_header(cell))
        # '시간' 열이 두 번 나오면 두 번째는 보통 소요시간 (예: 시간=MD, 시간=4:00)
        if field == "time_slot" and "time_slot" in mapping and "duration" not in mapping:
            field = "duration"
        if field and field not in mapping:
            mapping[field] = index
    return mapping


def _is_header(mapping):
    has_case = "surgery_name" in mapping or "patient_name" in mapping
    return "room" in mapping and has_case and len(mapping) >= 3


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell_text(value)
    if not text:
        return None
    match = re.search(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    try:
        return date_parser.parse(text, fuzzy=False).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _parse_duration(value):
    """60 / '60' / '90분' / '1:30' / '1시간 30분' / '2h' -> minutes."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if hasattr(value, "hour") and hasattr(value, "minute"):  # time / datetime cell
        return value.hour * 60 + value.minute
    text = _cell_text(value).lower()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:시간|h|hr|hour)", text)
    minutes = re.search(r"(\d+)\s*(?:분|m|min)", text)
    if hours or minutes:
        return int(float(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
    match = re.fullmatch(r"\d+(?:\.\d+)?", text)
    return int(float(text)) if match else 0


def _time_text(value):
    """Keep the institution's own notation (8A, TF1, 6P, 09:30) - only tidy real time cells."""
    if hasattr(value, "hour") and hasattr(value, "minute") and not isinstance(value, (int, float)):
        return f"{value.hour:02d}:{value.minute:02d}"
    return _cell_text(value)


def _status(value):
    text = _cell_text(value)
    return STATUS_MAP.get(text.replace(" ", ""), text or "예정")


def _find_sheet_date(rows, header_index, filename):
    """A date shown above the header (e.g. a title '2026-09-24 수술 스케줄') or in the file name."""
    for row in rows[:header_index]:
        for cell in row:
            found = _parse_date(cell) if isinstance(cell, (date, datetime)) else None
            if found is None:
                match = re.search(r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}", _cell_text(cell))
                found = _parse_date(match.group(0)) if match else None
            if found:
                return found
    match = re.search(r"(\d{4})[-._]?(\d{2})[-._]?(\d{2})", filename or "")
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return None


def parse_table_rows(rows, filename="", default_date=None):
    """rows: list of row lists (cell values). Returns a list of record dicts in the same
    shape Gemini extraction returns, or None if no recognizable header row was found."""
    rows = [list(r) for r in rows]
    header_index, mapping = None, None
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        candidate = _map_header(row)
        if _is_header(candidate):
            header_index, mapping = index, candidate
            break
    if mapping is None:
        return None

    sheet_date = _find_sheet_date(rows, header_index, filename) or default_date
    get = lambda row, field: row[mapping[field]] if field in mapping and mapping[field] < len(row) else None

    records = []
    last_room, last_date = "", sheet_date
    for row in rows[header_index + 1:]:
        if not any(_cell_text(c) for c in row):
            continue
        if _is_header(_map_header(row)):  # repeated header (e.g. per page)
            continue
        room = _cell_text(get(row, "room"))
        surgery = _cell_text(get(row, "surgery_name"))
        patient = _cell_text(get(row, "patient_name"))
        regnum = _cell_text(get(row, "regnum"))
        surgeon = _cell_text(get(row, "surgeon"))
        time_slot = _time_text(get(row, "time_slot"))

        # 공동 집도의 줄: 방·환자·등록번호·시간 없이 수술명/집도의만 반복 -> 위 케이스에 집도의 추가
        if records and not (room or patient or regnum or time_slot):
            if surgeon and surgeon not in records[-1]["surgeon"]:
                records[-1]["surgeon"] = ", ".join(filter(None, [records[-1]["surgeon"], surgeon]))
            continue
        if not (surgery or patient):
            continue

        row_date = _parse_date(get(row, "date")) if "date" in mapping else None
        row_date = row_date or last_date
        room = room or last_room  # 병합된 방 칸
        last_room, last_date = room, row_date

        info_parts = [p for p in (regnum, _cell_text(get(row, "patient_info"))) if p]
        age_sex = _cell_text(get(row, "age_sex"))
        patient_info = " ".join(info_parts)
        if age_sex:
            patient_info = f"{patient_info} ({age_sex})" if patient_info else age_sex

        records.append({
            "date": (row_date or date.today()).isoformat(),
            "room": room,
            "time_slot": time_slot,
            "surgery_name": surgery,
            "department": _cell_text(get(row, "department")),
            "surgeon": surgeon,
            "anesthesiologist": _cell_text(get(row, "anesthesiologist")),
            "duration": _parse_duration(get(row, "duration")),
            "patient_name": patient,
            "patient_info": patient_info,
            "status": _status(get(row, "status")),
        })
    return records or None


def parse_workbook(workbook, filename="", default_date=None):
    """First sheet with a recognizable table wins; returns None if none has one."""
    for sheet in workbook.worksheets:
        records = parse_table_rows(sheet.iter_rows(values_only=True), filename, default_date)
        if records:
            return records
    return None


def parse_delimited_text(text, filename="", default_date=None):
    """CSV / TSV text with a header row."""
    sample = text[:5000]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return parse_table_rows(rows, filename, default_date)
