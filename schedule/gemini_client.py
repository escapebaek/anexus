"""Turns an arbitrary schedule file (any institution's own Excel layout,
a plain-text memo, etc.) into a list of structured schedule records by
asking the Gemini API to read it and return JSON matching our schema.

This module only does extraction - it has no notion of "update" vs
"replace" and never sees the user's previously stored schedules. Deciding
whether an extracted record is the same case as an existing one (so its
memo should be kept) is done deterministically in Python, in
schedule/views.py, by comparing patient_name/surgery_name/surgeon. An
earlier version asked Gemini to make that same-case judgment itself
(matching against a list of existing schedules shown in the prompt), but
that turned out to be inconsistent in practice - the model's matching
decision could vary between calls even with few-shot examples, which
showed up as memos silently going missing after an "update" upload. A
plain Python equality check has no such variance.

Prose instructions alone were also inconsistent for the extraction task
itself across institutions' very different file formats (sometimes merging
a co-surgeon continuation row correctly, sometimes not; sometimes
prioritizing a registration number, sometimes not). Real input/output
examples are given as actual chat turns (few-shot / in-context learning)
rather than described in text, since that's markedly more reliable for
getting a consistent JSON shape out of an LLM than instructions alone.
"""
import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MAX_SOURCE_CHARS = 120_000

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

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "schedules": {"type": "ARRAY", "items": SCHEDULE_ITEM_SCHEMA},
    },
    "required": ["schedules"],
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
expected, including the trickiest case: merging a co-surgeon continuation row. Follow their \
formatting precisely - it's more reliable than the prose rules above when the two disagree on a \
fine point. In particular, keep "surgeon" and "surgery_name" worded exactly as they appear in the \
source (don't paraphrase/translate them) - the app matches re-uploaded files against previously \
stored schedules by comparing patient name, surgery name and surgeon as plain text, so consistent \
wording across uploads of the same institution's files matters more than it might seem.
"""

# Few-shot examples, given as actual prior conversation turns rather than described in prose -
# this is what keeps formatting (duration/status conversion, patient_info priority, the
# co-surgeon merge) consistent across wildly different institution file formats.
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


class ScheduleExtractionError(Exception):
    """Raised when Gemini can't be reached or its response isn't usable."""


def _example_turns():
    """Few-shot examples as alternating user/model turns."""
    turns = []
    for example in BASE_EXAMPLES:
        turns.append({"role": "user", "parts": [{"text": example["input"]}]})
        turns.append({
            "role": "model",
            "parts": [{"text": json.dumps({"schedules": example["output"]}, ensure_ascii=False)}],
        })
    return turns


def extract_schedules_from_text(source_text, source_filename=""):
    """Sends source_text to Gemini and returns a list of schedule record dicts."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ScheduleExtractionError("서버에 GEMINI_API_KEY가 설정되어 있지 않습니다. 관리자에게 문의하세요.")

    if len(source_text) > MAX_SOURCE_CHARS:
        raise ScheduleExtractionError("파일 내용이 너무 커서 처리할 수 없습니다. 파일을 나누어 업로드해주세요.")

    if not source_text.strip():
        raise ScheduleExtractionError("파일에서 읽을 수 있는 내용이 없습니다.")

    final_text = f"--- 업로드된 파일 ({source_filename}) 내용 ---\n{source_text}"

    contents = _example_turns()
    contents.append({"role": "user", "parts": [{"text": final_text}]})

    url = GEMINI_ENDPOINT.format(model=settings.GEMINI_MODEL)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTIONS}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            # Extraction should be a faithful transcription, not a creative task - low
            # temperature keeps free-text fields (patient_name, surgery_name, surgeon)
            # from varying between two calls on the same/near-identical input, which
            # matters a lot now that "update" matches on those fields as plain text.
            "temperature": 0,
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
