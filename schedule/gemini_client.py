"""Turns an arbitrary schedule file (any institution's own Excel layout,
a plain-text memo, etc.) into a list of structured schedule records by
asking the Gemini API to read it and return JSON matching our schema.

For "update" uploads, the caller also passes the user's currently stored
schedules. Gemini is shown that list and asked to say, per extracted entry,
whether it's the same real-world case as one of them (matched_existing_id)
or a new case. Matching is delegated to the model - rather than an exact
Python-side string match - because two files describing the same case can
word it differently (abbreviated surgery names, reformatted patient info,
a different room/time after reordering, etc.), and the same LLM that just
read both files is in the best position to tell "same case, reworded" apart
from "actually a different case".

Prose instructions alone were inconsistent across institutions' very
different file formats (sometimes merging a co-surgeon continuation row
correctly, sometimes not; sometimes prioritizing a registration number,
sometimes not). Real input/output examples are given as actual chat turns
(few-shot / in-context learning) rather than described in text, since that's
markedly more reliable for getting a consistent JSON shape out of an LLM
than instructions alone.
"""
import copy
import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MAX_SOURCE_CHARS = 120_000
MAX_EXISTING_SCHEDULES = 500

# 429 (quota) and 503 (model overloaded) are the codes Google's own docs call out as
# retryable - a short backoff clears most transient spikes without the user having to
# manually re-submit the form.
RETRYABLE_STATUS_CODES = {429, 503}
RETRY_BACKOFF_SECONDS = [2, 5]

SCHEDULE_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "date": {"type": "STRING", "description": "Surgery date, formatted as YYYY-MM-DD"},
        "room": {"type": "STRING", "description": "Operating room name or number"},
        "time_slot": {"type": "STRING", "description": "Start time, formatted as HH:MM (24h)"},
        "surgery_name": {"type": "STRING", "description": "Name of the surgery/procedure"},
        "department": {"type": "STRING", "description": "Medical department, empty string if unknown"},
        "surgeon": {"type": "STRING", "description": "Surgeon name, empty string if unknown"},
        "duration": {"type": "INTEGER", "description": "Expected duration in minutes, 0 if unknown"},
        "patient_name": {"type": "STRING"},
        "patient_info": {
            "type": "STRING",
            "description": (
                "Short patient identifier. If the source has a registration/chart/MRN number "
                "(등록번호, 병록번호, chart no.), ALWAYS include it here first - it's the most "
                "reliable way to recognize the same patient across different files. Combine with "
                "age/sex if both are present, e.g. '33258575 (F/45)'. Empty string if nothing is known."
            ),
        },
        "status": {
            "type": "STRING",
            "enum": ["예정", "진행중", "완료"],
            "description": "예정=scheduled/not started, 진행중=currently in surgery, 완료=finished. Default to 예정 if unclear.",
        },
    },
    "required": ["date", "room", "time_slot", "surgery_name", "duration", "patient_name", "status"],
}

SYSTEM_INSTRUCTIONS = """You are given the raw content of a hospital's surgery schedule file. \
The file may be a spreadsheet dump (rows/columns separated by tabs, possibly across multiple \
sheets) or a free-form text memo. Column names and layout vary by institution and are NOT fixed.

Extract every individual surgery/procedure entry you can find and return them as the \
"schedules" array described by the response schema. Rules:
- One entry per row/procedure. Ignore header rows, section titles, totals, and empty rows.
- Infer which column/field means what from context (dates, times, Korean medical department \
names, doctor names, patient names, etc.) even if headers are abbreviated or in a different \
order than expected.
- "date" must be YYYY-MM-DD. If the source only has a single date for the whole sheet (e.g. in \
a title), apply it to every row.
- "time_slot" must be HH:MM in 24-hour time.
- "duration" is in minutes as an integer (convert if source gives e.g. "1시간 30분" -> 90).
- "status" must be exactly one of 예정, 진행중, 완료 - map synonyms (e.g. "대기"->예정, \
"수술중"->진행중, "종료"/"완료"->완료) to the closest one, default 예정 if not stated.
- Leave a field as an empty string ("") rather than guessing if it truly isn't present.
- Do not invent surgeries that aren't in the source.
- Some exports include a "co-surgeon" continuation row directly below a real case: it repeats \
the same surgery_name/duration but has no room, patient name, or registration number of its own \
(it only exists to record a second operating surgeon). This is NOT a separate case - do not emit \
it as its own entry. Instead fold that surgeon's name into the "surgeon" field of the real case \
above it (e.g. "김철수, 박신균"), and skip the continuation row entirely.

The examples that follow (as prior turns in this conversation) show the exact input/output shape \
expected, including the two trickiest cases: merging a co-surgeon continuation row, and (in the \
last example) matching new entries against an existing schedule list. Follow their formatting \
precisely - it's more reliable than the prose rules above when the two disagree on a fine point.
"""

MATCH_RULES = """
추가로, 다음 요청에는 이 사용자가 현재 시스템에 이미 등록해 둔 수술 스케줄 목록이 함께 주어집니다 \
(JSON, 각 항목의 "id" 포함). 방금 추출한 각 항목에 대해, 이 목록 중 "같은 실제 케이스"(같은 환자가 \
받는 같은 수술)를 나타내는 기존 항목이 있는지 판단해서 matched_existing_id에 넣으세요.

두 파일은 표기 방식이 다를 수 있습니다 - 예를 들어 수술명이 "충수돌기절제술" / "충수돌기 절제술" / \
"Appendectomy"처럼 다르게 적혀 있거나, 환자 정보 표기가 다르거나(또는 한쪽에만 있거나), 날짜/방/시간/ \
상태가 바뀌었을 수 있습니다. 이런 표기·형식 차이는 무시하고, 같은 환자 + 같은 수술로 보이면 같은 \
케이스로 판단하세요. 마지막 예시가 이 판단 방식을 보여줍니다.

- 같은 케이스로 판단되면: matched_existing_id에 해당 기존 항목의 "id" 값을 문자열로 넣으세요.
- 새로 추가된 케이스이거나, 기존 목록의 항목과 같다고 확신할 수 없으면: matched_existing_id를 \
"NONE"으로 두세요.
- 기존 목록에는 있지만 새 파일에는 없는 항목(취소된 수술 등)은 신경 쓰지 않아도 됩니다. 그 항목에 대한 \
새 레코드를 만들지 마세요 - 그냥 언급하지 않으면 됩니다.
"""

# Few-shot examples, given as actual prior conversation turns rather than described in prose -
# this is what keeps formatting (duration/status conversion, patient_info priority, the
# co-surgeon merge, matched_existing_id judgment) consistent across wildly different institution
# file formats. Always shown, regardless of file type, since the input variety (table vs memo)
# is itself part of what they demonstrate.
BASE_EXAMPLES = [
    {
        "input": (
            "[Sheet: Sheet1]\n"
            "날짜\t방\t시간\t수술명\t진료과\t집도의\t수술시간\t환자명\t등록번호\t나이/성별\t상태\n"
            "2025-03-10\t3번방\t09:30\t복강경담낭절제술\t외과\t이민호\t1시간 30분\t정수현\t88213456\t52/M\t대기\n"
            "2025-03-10\t4번방\t11:00\t갑상선절제술\t외과\t박서준\t2:00\t김하은\t77120934\t45/F\t수술중\n"
        ),
        "output": [
            {
                "date": "2025-03-10", "room": "3번방", "time_slot": "09:30",
                "surgery_name": "복강경담낭절제술", "department": "외과", "surgeon": "이민호",
                "duration": 90, "patient_name": "정수현", "patient_info": "88213456 (52/M)",
                "status": "예정",
            },
            {
                "date": "2025-03-10", "room": "4번방", "time_slot": "11:00",
                "surgery_name": "갑상선절제술", "department": "외과", "surgeon": "박서준",
                "duration": 120, "patient_name": "김하은", "patient_info": "77120934 (45/F)",
                "status": "진행중",
            },
        ],
    },
    {
        "input": (
            "오늘 수술 메모\n"
            "7/25 1번방 아침 9시 - 홍길동(35/남) 충수돌기절제술 예정\n"
            "같은 방 오후 2시 - 박영희 담낭절제 진행중, 특이사항 없음\n"
        ),
        "output": [
            {
                "date": "2025-07-25", "room": "1번방", "time_slot": "09:00",
                "surgery_name": "충수돌기절제술", "department": "", "surgeon": "",
                "duration": 0, "patient_name": "홍길동", "patient_info": "35/남",
                "status": "예정",
            },
            {
                "date": "2025-07-25", "room": "1번방", "time_slot": "14:00",
                "surgery_name": "담낭절제", "department": "", "surgeon": "",
                "duration": 0, "patient_name": "박영희", "patient_info": "",
                "status": "진행중",
            },
        ],
    },
    {
        # The co-surgeon continuation row case that used to get extracted as a phantom,
        # room-less second entry - now folded into the real row's surgeon field.
        "input": (
            "날짜,방,시간,과,병실,등록번호,이름,성/나이,수술명,집도의,진단명,시간,현황\n"
            "2025-06-01,E1,MD,GS,054/19,71203438,배동규,M/42,부신절제술 (우측 / 개복),김남규,부신 우연종,4:00,대기\n"
            "2025-06-01,,,,,,,,부신절제술 (우측 / 개복),박신균,,4:00,\n"
        ),
        "output": [
            {
                "date": "2025-06-01", "room": "E1", "time_slot": "",
                "surgery_name": "부신절제술 (우측 / 개복)", "department": "GS",
                "surgeon": "김남규, 박신균", "duration": 240, "patient_name": "배동규",
                "patient_info": "71203438 (M/42)", "status": "예정",
            },
        ],
    },
]

# Shown only for "update" uploads (existing_schedules is non-empty). Demonstrates matching a
# reworded/moved case back to its existing id, and correctly leaving a genuinely new case
# unmatched, in the same response.
MATCH_EXAMPLE = {
    "existing": [
        {
            "id": 501, "date": "2025-06-01", "room": "E1", "time_slot": "",
            "surgery_name": "부신절제술 (우측 / 개복)", "department": "GS",
            "surgeon": "김남규, 박신균", "patient_name": "배동규",
            "patient_info": "71203438 (M/42)", "status": "예정",
        },
    ],
    "input": (
        "날짜,방,시간,과,병실,등록번호,이름,성/나이,수술명,집도의,진단명,시간,현황\n"
        "2025-06-01,E6,MD,GS,054/19,71203438,배동규,M/42,Adrenalectomy (open),김남규,부신 우연종,4:00,수술중\n"
        "2025-06-01,3번방,09:00,GS,010/02,90210111,최유진,F/29,복강경충수절제술,이지훈,급성충수염,1:00,대기\n"
    ),
    "output": [
        {
            "date": "2025-06-01", "room": "E6", "time_slot": "",
            "surgery_name": "Adrenalectomy (open)", "department": "GS", "surgeon": "김남규",
            "duration": 240, "patient_name": "배동규", "patient_info": "71203438 (M/42)",
            "status": "진행중", "matched_existing_id": "501",
        },
        {
            "date": "2025-06-01", "room": "3번방", "time_slot": "09:00",
            "surgery_name": "복강경충수절제술", "department": "GS", "surgeon": "이지훈",
            "duration": 60, "patient_name": "최유진", "patient_info": "90210111 (F/29)",
            "status": "예정", "matched_existing_id": "NONE",
        },
    ],
}


class ScheduleExtractionError(Exception):
    """Raised when Gemini can't be reached or its response isn't usable."""


def _schema_for(existing_ids):
    """Response schema, adding a matched_existing_id field constrained to the actual
    existing ids (plus "NONE") when there's something to match against, so Gemini can't
    hallucinate an id that doesn't exist. (Gemini rejects an empty string as an enum
    value, hence the "NONE" sentinel instead of "".)"""
    item_schema = copy.deepcopy(SCHEDULE_ITEM_SCHEMA)
    if existing_ids:
        item_schema["properties"]["matched_existing_id"] = {
            "type": "STRING",
            "enum": ["NONE"] + [str(i) for i in existing_ids],
            "description": (
                "The id of the existing schedule this entry is the same real-world case as, "
                "or \"NONE\" if it's a new case. See the matching rules and last example."
            ),
        }
        item_schema["required"] = item_schema["required"] + ["matched_existing_id"]
    return {
        "type": "OBJECT",
        "properties": {"schedules": {"type": "ARRAY", "items": item_schema}},
        "required": ["schedules"],
    }


def _example_turns(is_match_mode):
    """Few-shot examples as alternating user/model turns. Matches the response shape
    (with or without matched_existing_id) the live request will actually be constrained
    to, so the examples never contradict the schema in force for this call."""
    turns = []
    for example in BASE_EXAMPLES:
        turns.append({"role": "user", "parts": [{"text": example["input"]}]})
        turns.append({
            "role": "model",
            "parts": [{"text": json.dumps({"schedules": example["output"]}, ensure_ascii=False)}],
        })
    if is_match_mode:
        example_input = (
            "기존 등록된 스케줄 목록:\n"
            + json.dumps(MATCH_EXAMPLE["existing"], ensure_ascii=False, indent=2)
            + "\n\n--- 업로드된 파일 내용 ---\n"
            + MATCH_EXAMPLE["input"]
        )
        turns.append({"role": "user", "parts": [{"text": example_input}]})
        turns.append({
            "role": "model",
            "parts": [{"text": json.dumps({"schedules": MATCH_EXAMPLE["output"]}, ensure_ascii=False)}],
        })
    return turns


def extract_schedules_from_text(source_text, source_filename="", existing_schedules=None):
    """Sends source_text to Gemini and returns a list of schedule record dicts.

    existing_schedules, if given, is a list of dicts (each needs at least "id") describing
    the user's currently stored schedules; Gemini will annotate each returned record with
    a "matched_existing_id" pointing at the one it's the same case as, or "NONE" if it's new.
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ScheduleExtractionError("서버에 GEMINI_API_KEY가 설정되어 있지 않습니다. 관리자에게 문의하세요.")

    if len(source_text) > MAX_SOURCE_CHARS:
        raise ScheduleExtractionError("파일 내용이 너무 커서 처리할 수 없습니다. 파일을 나누어 업로드해주세요.")

    if not source_text.strip():
        raise ScheduleExtractionError("파일에서 읽을 수 있는 내용이 없습니다.")

    if existing_schedules and len(existing_schedules) > MAX_EXISTING_SCHEDULES:
        raise ScheduleExtractionError(
            "기존에 등록된 스케줄이 너무 많아 업데이트로 처리할 수 없습니다. '전체 교체'를 사용해주세요."
        )

    is_match_mode = bool(existing_schedules)
    existing_ids = [item["id"] for item in existing_schedules] if existing_schedules else []

    system_text = SYSTEM_INSTRUCTIONS + (MATCH_RULES if is_match_mode else "")

    final_text = ""
    if is_match_mode:
        existing_json = json.dumps(existing_schedules, ensure_ascii=False, indent=2)
        final_text += f"기존 등록된 스케줄 목록:\n{existing_json}\n\n"
    final_text += f"--- 업로드된 파일 ({source_filename}) 내용 ---\n{source_text}"

    contents = _example_turns(is_match_mode)
    contents.append({"role": "user", "parts": [{"text": final_text}]})

    url = GEMINI_ENDPOINT.format(model=settings.GEMINI_MODEL)
    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _schema_for(existing_ids),
        },
    }

    response = None
    for attempt, wait in enumerate([0] + RETRY_BACKOFF_SECONDS):
        if wait:
            time.sleep(wait)
        try:
            response = requests.post(url, params={"key": api_key}, json=payload, timeout=120)
        except requests.RequestException as exc:
            logger.error("Gemini API request failed: %s", exc)
            raise ScheduleExtractionError("Gemini API 호출에 실패했습니다. 잠시 후 다시 시도해주세요.") from exc
        if response.status_code == 200 or response.status_code not in RETRYABLE_STATUS_CODES:
            break
        logger.warning(
            "Gemini API returned %s (attempt %s/%s): %s",
            response.status_code, attempt + 1, len(RETRY_BACKOFF_SECONDS) + 1, response.text[:300],
        )

    if response.status_code != 200:
        logger.error("Gemini API returned %s: %s", response.status_code, response.text[:1000])
        if response.status_code == 429:
            raise ScheduleExtractionError(
                "Gemini API 사용량 한도를 초과했습니다. Google AI Studio에서 이 API 키가 연결된 "
                "프로젝트의 결제(요금제) 설정을 확인해주세요 - 무료 등급은 할당량이 매우 낮거나 "
                "0으로 설정되어 있을 수 있습니다."
            )
        if response.status_code == 503:
            raise ScheduleExtractionError(
                "Gemini 서버가 일시적으로 혼잡합니다 (모델 과부하). 잠시 후 다시 시도해주세요. "
                "계속 반복되면 API 키의 결제 설정을 확인해주세요."
            )
        raise ScheduleExtractionError(f"Gemini API 오류가 발생했습니다 (status {response.status_code}).")

    try:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        schedules = parsed["schedules"]
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        logger.error("Failed to parse Gemini response: %s / raw=%s", exc, response.text[:1000])
        raise ScheduleExtractionError("Gemini 응답을 해석하지 못했습니다. 파일 내용을 확인 후 다시 시도해주세요.") from exc

    if not isinstance(schedules, list):
        raise ScheduleExtractionError("Gemini 응답 형식이 올바르지 않습니다.")

    if not schedules:
        raise ScheduleExtractionError("파일에서 수술 일정을 찾지 못했습니다.")

    return schedules
