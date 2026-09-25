"""AI extraction across several free providers, tried in order.

Only needed for files table_parser.py can't read by column name (free-form memos,
unusual layouts). Providers are tried in SCHEDULE_AI_PROVIDERS order, skipping any
without an API key; each provider also walks its own list of models, so one busy
model or an exhausted free quota doesn't fail the upload.

- groq / openrouter: OpenAI-compatible chat completions API (free tiers, no card).
  Groq is very fast but its free tier caps tokens per minute, so it suits small
  files; bigger tables are normally handled by table_parser without AI.
- gemini: see gemini_client.py.
"""
import hashlib
import json
import logging
import re
import time

import requests
from django.conf import settings

from . import gemini_client
from .gemini_client import BASE_EXAMPLES, MAX_SOURCE_CHARS, SCHEDULE_ITEM_SCHEMA, SYSTEM_INSTRUCTIONS, ScheduleExtractionError

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_setting": "GROQ_API_KEY",
        "models_setting": "GROQ_MODELS",
        "label": "Groq",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_setting": "OPENROUTER_API_KEY",
        "models_setting": "OPENROUTER_MODELS",
        "label": "OpenRouter",
    },
}
PER_REQUEST_TIMEOUT_SECONDS = 90
# 모델을 건너뛸 응답: 과부하/한도 초과/없는 모델/요청이 너무 큼(무료 토큰 한도)
SKIP_STATUS_CODES = {404, 408, 413, 422, 429, 500, 502, 503, 504}

_FIELDS = ", ".join(SCHEDULE_ITEM_SCHEMA["properties"])
JSON_INSTRUCTIONS = (
    SYSTEM_INSTRUCTIONS
    + "\n\nRespond with ONLY a JSON object of the form {\"schedules\": [ ... ]}, where each item has "
    f"exactly these keys: {_FIELDS}. \"duration\" is an integer; every other value is a string "
    "(use \"\" when unknown). No markdown, no explanations."
)


def configured_providers():
    """Providers from SCHEDULE_AI_PROVIDERS that have an API key set."""
    order = [p.strip().lower() for p in str(settings.SCHEDULE_AI_PROVIDERS or "").split(",") if p.strip()]
    result = []
    for name in order:
        if name == "gemini" and settings.GEMINI_API_KEY:
            result.append(name)
        elif name in OPENAI_COMPATIBLE and getattr(settings, OPENAI_COMPATIBLE[name]["key_setting"], ""):
            result.append(name)
    return result


KEY_HELP = {
    "groq": ("GROQ_API_KEY", "https://console.groq.com"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/keys"),
    "gemini": ("GEMINI_API_KEY", "https://aistudio.google.com/apikey"),
}


def unconfigured_providers():
    """SCHEDULE_AI_PROVIDERS 에 있지만 API 키가 없어 건너뛰는 제공자들."""
    order = [p.strip().lower() for p in str(settings.SCHEDULE_AI_PROVIDERS or "").split(",") if p.strip()]
    configured = set(configured_providers())
    return [name for name in order if name in KEY_HELP and name not in configured]


def _missing_key_hint():
    missing = unconfigured_providers()
    if not missing:
        return ""
    keys = ", ".join(f"{KEY_HELP[name][0]} ({KEY_HELP[name][1]})" for name in missing)
    return (f" ※ 지금은 {', '.join(n.capitalize() for n in configured_providers()) or '없음'} 만 사용 중입니다. "
            f"서버 환경변수에 {keys} 를 무료로 발급받아 추가하면, 한도가 찼을 때 자동으로 넘어가 분석합니다.")


def _models(name):
    raw = getattr(settings, OPENAI_COMPATIBLE[name]["models_setting"], "") or ""
    return [m.strip() for m in raw.split(",") if m.strip()]


def _parse_json_schedules(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])
    schedules = parsed.get("schedules") if isinstance(parsed, dict) else parsed
    if not isinstance(schedules, list):
        raise ValueError("no schedules list")
    return [s for s in schedules if isinstance(s, dict)]


def _openai_compatible(name, source_text, filename, deadline):
    conf = OPENAI_COMPATIBLE[name]
    api_key = getattr(settings, conf["key_setting"])
    messages = [{"role": "system", "content": JSON_INSTRUCTIONS}]
    for example in BASE_EXAMPLES:
        messages.append({"role": "user", "content": example["input"]})
        messages.append({"role": "assistant", "content": json.dumps({"schedules": example["output"]}, ensure_ascii=False)})
    messages.append({"role": "user", "content": f"--- 업로드된 파일 ({filename}) 내용 ---\n{source_text}"})

    failures = []
    for model in _models(name):
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        try:
            response = requests.post(
                f"{conf['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                timeout=min(PER_REQUEST_TIMEOUT_SECONDS, remaining),
            )
        except requests.Timeout:
            failures.append(f"{model}: 시간 초과")
            continue
        except requests.RequestException as exc:
            logger.warning("%s request failed: %s", name, exc)
            failures.append(f"{model}: 연결 실패")
            continue

        if response.status_code in (401, 403):
            raise ScheduleExtractionError(f"{conf['label']} API 키가 올바르지 않습니다 ({conf['key_setting']} 확인).")
        if response.status_code != 200:
            logger.warning("%s model %s returned %s: %s", name, model, response.status_code, response.text[:300])
            failures.append(f"{model}: {response.status_code}")
            if response.status_code in SKIP_STATUS_CODES or response.status_code == 400:
                continue
            break
        try:
            content = response.json()["choices"][0]["message"]["content"]
            schedules = _parse_json_schedules(content)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("%s model %s gave unparseable output: %s", name, model, exc)
            failures.append(f"{model}: 응답 해석 실패")
            continue
        if schedules:
            return schedules
        failures.append(f"{model}: 일정 없음")
    raise ScheduleExtractionError(f"{conf['label']} 무료 모델들이 응답하지 않았습니다 ({'; '.join(failures) or '시간 부족'}).")


def extract_schedules(source_text, filename=""):
    """Tries each configured provider in order; returns the first non-empty result."""
    if not source_text.strip():
        raise ScheduleExtractionError("파일에서 읽을 수 있는 내용이 없습니다.")
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ScheduleExtractionError("파일 내용이 너무 커서 처리할 수 없습니다. 파일을 나누어 업로드해주세요.")
    providers = configured_providers()
    if not providers:
        raise ScheduleExtractionError(
            "이 파일은 표(열 이름) 형식이 아니라 AI 분석이 필요한데, 서버에 AI API 키가 설정되어 있지 않습니다. "
            "GROQ_API_KEY 또는 GEMINI_API_KEY 를 설정하거나, 날짜·방·시간·수술명·환자명 열이 있는 엑셀로 올려주세요."
        )

    deadline = time.monotonic() + settings.SCHEDULE_AI_TIME_BUDGET
    errors = []
    for name in providers:
        if deadline - time.monotonic() < 5:
            break
        try:
            if name == "gemini":
                return gemini_client.extract_schedules_from_text(source_text, filename)
            return _openai_compatible(name, source_text, filename, deadline)
        except ScheduleExtractionError as exc:
            logger.warning("AI provider %s failed: %s", name, exc)
            errors.append(str(exc))
    raise ScheduleExtractionError(
        (" / ".join(errors) or "AI 분석 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.") + _missing_key_hint())


# ---------- 작은 질문: 예상 수술 시간 열 찾기 ----------
# 표 형식 업로드에서 열 이름 규칙으로 예상 시간 열을 못 찾았을 때만, 남은 열 이름과 시간처럼 생긴
# 예시 값만 보내 묻는다 (환자 정보는 보내지 않음). 업로드 요청 안에서 기다리므로 짧게 끝낸다.
COLUMN_QUESTION_BUDGET_SECONDS = 12
COLUMN_HINT_CACHE_SECONDS = 60 * 60 * 24 * 30

COLUMN_QUESTION = (
    "You help read hospital operating-room schedule tables. Given the columns a program could not "
    "identify (header text plus a few sample values; '(글자)' means a non-numeric text value), decide "
    "which single column holds the EXPECTED/PLANNED length of each surgery (e.g. 90, '1:30', '2시간'), "
    "or, if there is none, which column holds the PLANNED END time of each surgery (e.g. '11:30'). "
    "Do not pick start times, dates, ages, room numbers, sequence numbers or registration numbers. "
    'Respond with ONLY JSON: {"index": <column index or null>, "kind": "duration" | "end_time" | null}.'
)


def _ask_gemini_json(system, prompt, timeout):
    response = requests.post(
        gemini_client.GEMINI_ENDPOINT.format(model=settings.GEMINI_MODEL),
        params={"key": settings.GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ask_openai_compatible_json(name, system, prompt, timeout):
    conf = OPENAI_COMPATIBLE[name]
    models = _models(name)
    if not models:
        raise ValueError("no model")
    response = requests.post(
        f"{conf['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {getattr(settings, conf['key_setting'])}", "Content-Type": "application/json"},
        json={"model": models[0], "temperature": 0, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def ask_json(system, prompt, budget=COLUMN_QUESTION_BUDGET_SECONDS):
    """짧은 질문 하나를 설정된 AI 에 차례로 묻고 JSON 객체를 돌려줌. 모두 실패하면 None."""
    deadline = time.monotonic() + budget
    for name in configured_providers():
        remaining = deadline - time.monotonic()
        if remaining < 2:
            break
        try:
            if name == "gemini":
                text = _ask_gemini_json(system, prompt, remaining)
            else:
                text = _ask_openai_compatible_json(name, system, prompt, remaining)
            text = (text or "").strip()
            fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
            parsed = json.loads(fenced.group(1) if fenced else text)
            if isinstance(parsed, dict):
                return parsed
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("AI column question via %s failed: %s", name, exc)
    return None


def find_duration_column(candidates):
    """candidates: [{"index", "header", "samples"}] -> (index, "duration" | "end_time") or None.
    같은 머리글 구성의 답은 기억해 두어, 같은 병원 양식을 다시 올릴 때는 AI 를 부르지 않음."""
    from django.core.cache import cache

    key = "schedule:duration-col:" + json.dumps([c["header"] for c in candidates], ensure_ascii=False)
    key = key if len(key) < 200 else "schedule:duration-col:" + hashlib.sha1(key.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return tuple(cached) if cached else None
    if not configured_providers():
        return None
    lines = [f'{c["index"]}: "{c["header"]}" 예시 {c["samples"]}' for c in candidates]
    answer = ask_json(COLUMN_QUESTION, "Columns:\n" + "\n".join(lines))
    if answer is None:
        return None  # 실패는 기억하지 않음 (다음 업로드 때 다시 시도)
    index, kind = answer.get("index"), answer.get("kind")
    result = (index, kind) if isinstance(index, int) and kind in ("duration", "end_time") else ()
    cache.set(key, list(result), COLUMN_HINT_CACHE_SECONDS)
    return result or None
