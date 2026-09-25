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
    "anesthesiologist": ["마취의", "마취과", "마취담당", "마취담당의", "마취과의사", "담당마취의", "anesthesiologist"],
    "anesthesia_type": ["마취방법", "마취종류", "마취법", "마취형태", "마취유형", "마취방식", "anesthesiatype"],
    # '마취' 한 단어 열: 값이 마취 방법(전신/척추/MAC...)이면 방법, 아니면 마취의 이름으로 봄
    "anesthesia_either": ["마취"],
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

# 마취 방법 코드와 이를 가리키는 표기들 (소문자, 공백/구두점 제거 후 비교)
ANESTHESIA_TYPES = {
    "CSE": ["cse", "척추경막외", "척추경막외병용", "combinedspinalepidural", "combined"],
    "GA": ["ga", "g/a", "전신", "전신마취", "general", "generalanesthesia", "ett", "lma", "tiva", "기관삽관"],
    "SA": ["sa", "s/a", "척추", "척추마취", "척수", "척수마취", "spinal", "spinalanesthesia"],
    "EA": ["ea", "e/a", "경막외", "경막외마취", "epidural", "epiduralanesthesia"],
    "BL": ["bl", "block", "nerveblock", "신경차단", "신경블록", "블록", "상완신경총", "bpb", "pnb", "regional", "부위마취"],
    "MAC": ["mac", "감시하마취관리", "감시", "진정", "sedation", "macsedation", "monitoredanesthesiacare", "iv sedation", "ivsedation"],
    "LA": ["la", "l/a", "국소", "국소마취", "local", "localanesthesia"],
}
_ANESTHESIA_LOOKUP = {re.sub(r"[\s/()\[\]._\-·:+]+", "", alias): code
                      for code, aliases in ANESTHESIA_TYPES.items() for alias in aliases}


def normalize_anesthesia(value, keep_unknown=True):
    """'전신' / 'General (ETT)' / 'S/A' / 'MAC/sedation' -> GA / SA / MAC ...
    Unknown text is kept as-is (trimmed to 20 chars) unless keep_unknown=False (-> '')."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    key = re.sub(r"[\s/()\[\]._\-·:+]+", "", text).lower()
    if key in _ANESTHESIA_LOOKUP:
        return _ANESTHESIA_LOOKUP[key]
    if text.upper() in ANESTHESIA_TYPES:
        return text.upper()
    # 'General (ETT)', '전신(LMA)', 'Spinal + sedation' 처럼 앞부분이 방법인 경우
    # (짧은 영문 약어 GA/SA 등은 다른 단어의 앞부분일 수 있어 제외: 영문 3자 이상, 한글 2자 이상만)
    for alias, code in sorted(_ANESTHESIA_LOOKUP.items(), key=lambda kv: -len(kv[0])):
        long_enough = len(alias) >= (3 if alias.isascii() else 2)
        if long_enough and key.startswith(alias):
            return code
    return text[:20] if keep_unknown else ""


def _norm_header(value):
    """'수술실(호)' -> '수술실', 'Anes. Dr' -> 'anesdr', 'Room #' -> 'room' (괄호 속 단위·부연 설명 제거)."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", str(value or ""))
    return re.sub(r"[\s/()\[\]._\-·:#*]+", "", text).lower()


# 열 이름 규칙 (위에서부터 먼저 맞는 것). 정확히 일치하는 HEADER_SYNONYMS 로 못 찾을 때 사용.
# 병실·진단명 같은 열이 방·수술명으로 잘못 읽히지 않도록 'ignore' 를 가장 먼저 둠.
HEADER_RULES = [
    ("ignore", r"병실|병동|ward|^bed|진단|diagnos|^dx|비고|remark|^note|메모|주소|전화|phone|연락처|보험|insurance|체중|weight|^키$|height|혈액형|bloodtype|^no$|^번호$|^순$"),
    ("anesthesia_type", r"마취(방법|종류|법|형태|유형|방식|구분)|anes\w*type|anaes\w*type|anesthetictype|마취type"),
    ("anesthesiologist", r"마취(의|의사|과|과의사|과의|담당|담당의|전문의|과담당의?|과선생님)$|담당마취|anesthesiologist|anaesthetist|anesthetist|anes\w*(dr|doctor|md|provider|staff|attending|physician)"),
    ("anesthesia_either", r"^마취$|^anes$|^anesth$|^anesthesia$|^anaesthesia$|^anesthetic$"),
    # 종료(예정) 시각 열: 예상 시간 열이 없을 때 시작 시각과의 차이로 예상 시간을 계산
    ("end_time", r"종료|끝나는|^끝$|^end(time)?$|^finish|endtime|finishtime|^to$"),
    ("duration", r"소요|예상시간|예상소요|수술시간|duration|^dur$|length|optime|^mins?$|^분$|esttime|estimated"),
    ("date", r"날짜|일자|^수술일|^일$|^date|opdate|surgerydate|casedate|^day$"),
    ("regnum", r"등록번호|병록|차트|환자번호|환자id|mrn|chart|regno|registration|unitno|hospno|patientid|^ptid$|^id$"),
    ("age_sex", r"성별|나이|연령|^age|^sex|gender|^sa$|^mf$"),
    ("patient_info", r"환자정보|^정보$|patientinfo|ptinfo"),
    ("patient_name", r"환자명|환자성명|환자이름|수진자|^성명$|^이름$|^환자$|^pt$|ptname|patientname|^patient$|^name$"),
    ("surgeon", r"집도|주치의|수술의|operator|surgeon|^opdr|^opdoctor|주수술"),
    ("department", r"진료과|^과$|과명$|^과목|dept|department|^service|specialty"),
    ("room", r"수술실|수술방|^방|방번호|^룸|^실$|room|^rm|theat|^(or|ot)(no|number|rm)?\d*$"),
    ("time_slot", r"시간|시각|시작|time|start|slot"),
    ("sequence", r"순서|순번|^seq|order|^차례"),
    ("surgery_name", r"수술명|^수술$|수술내용|술식|시술|procedure|operation|surgery|^op(name|title)?$|^case(name)?$"),
    ("status", r"상태|현황|진행|status|progress|state"),
]
_HEADER_RULES = [(field, re.compile(pattern)) for field, pattern in HEADER_RULES]

FIELD_LABELS = {
    "date": "날짜", "room": "방", "time_slot": "시간", "sequence": "순서", "duration": "소요시간", "end_time": "종료시각",
    "surgery_name": "수술명", "department": "과", "surgeon": "집도의", "anesthesiologist": "마취의",
    "anesthesia_type": "마취방법", "anesthesia_either": "마취", "patient_name": "환자명", "regnum": "등록번호",
    "age_sex": "성별/나이", "patient_info": "환자정보", "status": "상태",
}


def classify_header(cell):
    """One header cell -> field name, 'ignore', or None (unknown)."""
    key = _norm_header(cell)
    if not key:
        return None
    field = _SYNONYM_TO_FIELD.get(key)
    if field:
        return field
    for field, pattern in _HEADER_RULES:
        if pattern.search(key):
            return field
    return None


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _map_header(row):
    """{field: column index} for a candidate header row (first column wins per field),
    plus 'age_sex' may collect several columns (성별 + 나이) under '_age_sex_cols'."""
    mapping = {}
    for index, cell in enumerate(row):
        field = classify_header(cell)
        if field in (None, "ignore"):
            continue
        # '시간' 열이 두 번 나오면 두 번째는 보통 소요시간 (예: 시간=MD, 시간=4:00)
        if field == "time_slot" and "time_slot" in mapping and "duration" not in mapping \
                and _norm_header(cell) in ("시간", "time"):
            field = "duration"
        if field == "age_sex":
            mapping.setdefault("_age_sex_cols", []).append(index)
        if field not in mapping:
            mapping[field] = index
    # 시각 열이 없으면 순번/순서 열을 시간 칸에 표시
    if "time_slot" not in mapping and "sequence" in mapping:
        mapping["time_slot"] = mapping["sequence"]
    return mapping


def _is_header(mapping):
    fields = {k for k in mapping if not k.startswith("_")}
    has_case = "surgery_name" in mapping or "patient_name" in mapping
    return "room" in mapping and has_case and len(fields) >= 3


def _header_report(row, mapping):
    """(읽은 열 설명 목록, 사용하지 않은 열 이름 목록) - 업로드 결과 안내용."""
    used_cols = {index: field for field, index in mapping.items() if not field.startswith("_")}
    for index in mapping.get("_age_sex_cols", []):
        used_cols.setdefault(index, "age_sex")
    used, unused = [], []
    for index, cell in enumerate(row):
        name = _cell_text(cell)
        if not name:
            continue
        if index in used_cols:
            label = FIELD_LABELS.get(used_cols[index], used_cols[index])
            if index in mapping.get("_ai_cols", ()):
                label += "(AI)"
            used.append(name if _norm_header(name) == _norm_header(label) else f"{name}→{label}")
        else:
            unused.append(name)
    return used, unused


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


def clock_minutes(value):
    """'09:30' / '9시 30분' / '8A' / '1:30P' / '2 PM' / time cell -> minutes after midnight, or None."""
    if value is None or isinstance(value, (int, float)):
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value.hour * 60 + value.minute
    text = _cell_text(value).lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?(a|p|am|pm|오전|오후)?", text)
    if match:
        hour, minute, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if half is None and match.group(2) is None:
            return None  # 숫자 하나('3')는 순번일 수 있음
    else:
        match = re.fullmatch(r"(오전|오후)?(\d{1,2})시(?:(\d{1,2})분)?", text)
        if not match:
            return None
        half, hour, minute = match.group(1), int(match.group(2)), int(match.group(3) or 0)
    if half in ("p", "pm", "오후") and hour < 12:
        hour += 12
    elif half in ("a", "am", "오전") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def duration_from_times(start, end):
    """시작·종료(예정) 시각 -> 분. 자정을 넘기면 다음 날로 봄. 알 수 없으면 0."""
    start, end = clock_minutes(start), clock_minutes(end)
    if start is None or end is None:
        return 0
    minutes = end - start if end > start else end + 24 * 60 - start
    return minutes if 0 < minutes <= 16 * 60 else 0


def plausible_duration_column(values, kind, starts=()):
    """AI 가 고른 열이 정말 예상 시간(또는 종료 시각)인지 값으로 확인: 절반 이상이 5분~24시간."""
    values = list(values)
    filled = [i for i, v in enumerate(values) if _cell_text(v)]
    if not filled:
        return False
    if kind == "duration":
        ok = [i for i in filled if 5 <= _parse_duration(values[i]) <= 24 * 60]
    else:
        starts = list(starts)
        ok = [i for i in filled if i < len(starts) and duration_from_times(starts[i], values[i]) >= 5]
    return len(ok) * 2 >= len(filled)


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


SECTION_ROOM_RE = re.compile(r"^(?:\d+\s*번?\s*(?:방|실|호실?)|(?:or|room|rm|수술실)\s*[-#]?\s*[a-z]?\d+[a-z]?|[a-z]\d{1,3})$", re.I)


def _merge_header_rows(upper, lower):
    """두 줄로 된 머리글 (예: 윗줄 '환자' / 아랫줄 '이름','번호') 을 한 줄로 합침."""
    merged = []
    last_up = ""
    for i in range(max(len(upper), len(lower))):
        up = _cell_text(upper[i]) if i < len(upper) else ""
        # 병합된 윗칸('환자' 가 '이름'·'번호' 두 칸에 걸침)은 첫 칸에만 값이 있으므로 옆으로 이어받음
        up = up or last_up
        last_up = up
        low = _cell_text(lower[i]) if i < len(lower) else ""
        choice = up
        for candidate in (low, up + low, up):
            if candidate and classify_header(candidate) not in (None, "ignore"):
                choice = candidate
                break
        merged.append(choice or low)
    return merged


def _find_header(rows):
    """-> (data start index, header cells, mapping) or (None, None, None)."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        candidates = [(row, _map_header(row))]
        if index > 0:
            merged = _merge_header_rows(rows[index - 1], row)
            candidates.append((merged, _map_header(merged)))
        best = max(candidates, key=lambda c: len([k for k in c[1] if not k.startswith("_")]))
        if _is_header(best[1]):
            return index, best[0], best[1]
    return None, None, None


def _find_duration_column(rows, header_index, header, mapping, resolve_duration):
    """규칙으로 예상 시간/종료 시각 열을 못 찾았을 때, 남은 열 이름과 예시 값을 resolve_duration 에
    보여주고(AI) 답을 값으로 검증해 mapping 에 추가."""
    used = {i for k, i in mapping.items() if not k.startswith("_") and isinstance(i, int)}
    used.update(mapping.get("_age_sex_cols", []))
    data_rows = [r for r in rows[header_index + 1:header_index + 41] if any(_cell_text(c) for c in r)]
    column = lambda i: [r[i] if i < len(r) else None for r in data_rows]
    candidates = []
    for index, cell in enumerate(header):
        name = _cell_text(cell)
        if not name or index in used:
            continue
        samples = [_cell_text(v) for v in column(index) if _cell_text(v)][:4]
        # 환자 정보가 AI 로 나가지 않도록 시간·숫자처럼 생긴 값만 보여줌
        samples = [v if re.search(r"\d", v) and re.fullmatch(r"[\d\s:.~\-/()apmhrsinAPMHRSIN시간분오전후]{1,16}", v) else "(글자)" for v in samples]
        candidates.append({"index": index, "header": name, "samples": samples})
    if not candidates:
        return
    try:
        answer = resolve_duration(candidates)
    except Exception:
        return
    if not answer:
        return
    index, kind = answer
    if kind not in ("duration", "end_time") or index not in {c["index"] for c in candidates}:
        return
    starts = column(mapping["time_slot"]) if "time_slot" in mapping else []
    if kind == "end_time" and not starts:
        return
    if plausible_duration_column(column(index), kind, starts):
        mapping[kind] = index
        mapping["_ai_cols"] = {index}


def parse_table_rows(rows, filename="", default_date=None, report=None, resolve_duration=None):
    """rows: list of row lists (cell values). Returns a list of record dicts in the same
    shape AI extraction returns, or None if this isn't a table we can read reliably
    (then the caller falls back to AI). `report`, if given, is filled with the columns
    used / not used and, on None, the reason."""
    rows = [list(r) for r in rows]
    report = report if report is not None else {}
    header_index, header, mapping = _find_header(rows)
    if mapping is None:
        report["reason"] = "열 이름(방·수술명 등)이 있는 머리글 줄을 찾지 못했습니다."
        return None
    if resolve_duration and "surgery_name" in mapping and "duration" not in mapping and "end_time" not in mapping:
        _find_duration_column(rows, header_index, header, mapping, resolve_duration)
    used, unused = _header_report(header, mapping)
    report.update(used=used, unused=unused)
    # 수술명 열이 없거나, 환자 열을 못 찾았는데 모르는 열이 남아 있으면 표로 읽지 않고 AI 에 맡김
    # (그 모르는 열이 환자 이름일 수 있어서 - 빠뜨린 채 반영하면 메모 연결이 깨짐)
    if "surgery_name" not in mapping:
        report["reason"] = "수술명 열을 찾지 못했습니다."
        return None
    if "patient_name" not in mapping and "regnum" not in mapping and unused:
        report["reason"] = "환자 이름/번호 열을 확실히 찾지 못했습니다."
        return None

    sheet_date = _find_sheet_date(rows, header_index, filename) or default_date
    get = lambda row, field: row[mapping[field]] if field in mapping and mapping[field] < len(row) else None

    records = []
    last_room, last_date = "", sheet_date
    for row in rows[header_index + 1:]:
        cells = [_cell_text(c) for c in row]
        filled = [c for c in cells if c]
        if not filled:
            continue
        if _is_header(_map_header(row)):  # repeated header (e.g. per page)
            continue
        # 표 중간의 구분 줄: 칸 하나에 날짜('2026-09-24') 나 방('3번방', 'OR 5') 만 있는 경우
        if len(filled) == 1 and not _cell_text(get(row, "surgery_name")) and not _cell_text(get(row, "patient_name")):
            section_date = _parse_date(filled[0]) if re.search(r"\d{4}|\d{1,2}[/.월]\d{1,2}", filled[0]) else None
            if section_date:
                last_date = section_date
            elif SECTION_ROOM_RE.match(filled[0]):
                last_room = filled[0]
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
        age_sex = "/".join(filter(None, (_cell_text(row[i]) for i in mapping.get("_age_sex_cols", []) if i < len(row))))
        patient_info = " ".join(info_parts)
        if age_sex:
            patient_info = f"{patient_info} ({age_sex})" if patient_info else age_sex

        anesthesiologist = _cell_text(get(row, "anesthesiologist"))
        anesthesia_type = normalize_anesthesia(get(row, "anesthesia_type"))
        either = _cell_text(get(row, "anesthesia_either"))
        if either:
            code = normalize_anesthesia(either, keep_unknown=False)
            if code and not anesthesia_type:
                anesthesia_type = code
            elif not code and not anesthesiologist:
                anesthesiologist = either

        records.append({
            "date": (row_date or date.today()).isoformat(),
            "room": room,
            "time_slot": time_slot,
            "surgery_name": surgery,
            "department": _cell_text(get(row, "department")),
            "surgeon": surgeon,
            "anesthesiologist": anesthesiologist,
            "anesthesia_type": anesthesia_type,
            "duration": _parse_duration(get(row, "duration"))
                        or duration_from_times(get(row, "time_slot"), get(row, "end_time")),
            "patient_name": patient,
            "patient_info": patient_info,
            "status": _status(get(row, "status")),
        })
    if not records:
        report["reason"] = "머리글 아래에서 수술 행을 찾지 못했습니다."
    return records or None


def parse_workbook(workbook, filename="", default_date=None, report=None, resolve_duration=None):
    """First sheet with a recognizable table wins; returns None if none has one."""
    report = report if report is not None else {}
    for sheet in workbook.worksheets:
        sheet_report = {}
        records = parse_table_rows(sheet.iter_rows(values_only=True), filename, default_date, sheet_report,
                                   resolve_duration)
        report.clear()
        report.update(sheet_report)
        if records:
            return records
    return None


def parse_delimited_text(text, filename="", default_date=None, report=None, resolve_duration=None):
    """CSV / TSV text with a header row."""
    sample = text[:5000]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return parse_table_rows(rows, filename, default_date, report, resolve_duration)
