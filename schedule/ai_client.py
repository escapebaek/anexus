"""AI extraction across several free providers, tried in order.

Only needed for files table_parser.py can't read by column name (free-form memos,
unusual layouts). Providers are tried in SCHEDULE_AI_PROVIDERS order, skipping any
without an API key; each provider also walks its own list of models, so one busy
model or an exhausted free quota doesn't fail the upload.

- localai: 직접 띄운 로컬 AI 서버 (Qwen, Tailscale). 지금은 이것만 사용 (settings.py 참고).
- groq / openrouter: OpenAI-compatible chat completions API (free tiers, no card). [사용 중지]
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
    "localai": {
        "url_setting": "LOCALAI_URL",           # 주소는 설정에서 (서버를 옮겨도 코드 수정 없음)
        "key_setting": "LOCALAI_API_KEY",
        "models_setting": "LOCALAI_MODEL",
        "timeout_setting": "LOCALAI_TIMEOUT",
        "label": "로컬 AI",
    },
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
    """Providers from SCHEDULE_AI_PROVIDERS that have an API key set (localai: 주소와 키)."""
    order = [p.strip().lower() for p in str(settings.SCHEDULE_AI_PROVIDERS or "").split(",") if p.strip()]
    result = []
    for name in order:
        if name == "gemini" and settings.GEMINI_API_KEY:
            result.append(name)
        elif name in OPENAI_COMPATIBLE and getattr(settings, OPENAI_COMPATIBLE[name]["key_setting"], ""):
            url_setting = OPENAI_COMPATIBLE[name].get("url_setting")
            if url_setting is None or getattr(settings, url_setting, ""):
                result.append(name)
    return result


def _base_url(name):
    conf = OPENAI_COMPATIBLE[name]
    if "url_setting" not in conf:
        return conf["base_url"]
    url = str(getattr(settings, conf["url_setting"], "") or "").strip().rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


def _timeout(name, default=None):
    setting = OPENAI_COMPATIBLE[name].get("timeout_setting")
    return getattr(settings, setting) if setting else (default or PER_REQUEST_TIMEOUT_SECONDS)


def _headers(name):
    key = getattr(settings, OPENAI_COMPATIBLE[name]["key_setting"])
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if name == "localai":
        # 직접 만든 게이트웨이는 키를 받는 헤더가 제각각이라 흔한 방식을 함께 보냄 (같은 서버로만 감)
        header = (settings.LOCALAI_AUTH_HEADER or "").strip()
        if not header:
            headers.update({"X-API-Key": key, "api-key": key})
        elif header.lower() != "authorization":
            headers.pop("Authorization")
            headers[header] = key
    return headers


def _extra_body(name):
    """로컬 Qwen: 생각 모드(<think>)를 꺼서 빠르게. 모르는 서버는 이 값을 무시함."""
    if name == "localai":
        think = bool(settings.LOCALAI_THINKING)
        # think: escapebaek/localapi 게이트웨이 확장 / chat_template_kwargs: vLLM·llama.cpp 방식
        return {"think": think, "chat_template_kwargs": {"enable_thinking": think}}
    return {}


def _post_chat(name, model, messages, timeout, json_mode=True):
    """chat/completions 호출. 로컬 서버가 JSON 모드·추가 옵션을 모르면(400) 빼고 한 번 더."""
    body = {"model": model, "messages": messages, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    body.update(_extra_body(name))
    url = f"{_base_url(name)}/chat/completions"
    response = requests.post(url, headers=_headers(name), json=body, timeout=timeout)
    if response.status_code == 400 and name == "localai" and len(body) > 3:
        logger.info("localai rejected optional fields, retrying plain: %s", response.text[:200])
        plain = {"model": model, "messages": messages, "temperature": 0}
        response = requests.post(url, headers=_headers(name), json=plain, timeout=timeout)
    return response


THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def clean_content(text):
    """모델 답에서 생각 과정(<think>…</think>)과 ```json 울타리를 걷어냄."""
    text = THINK_RE.sub("", text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return fenced.group(1).strip() if fenced else text


KEY_HELP = {
    "localai": ("LOCALAI_URL, LOCALAI_API_KEY", "로컬 AI 서버"),
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


_discovered_models = {}
_discovery_errors = {}   # 마지막으로 모델 목록을 못 가져온 이유 (화면 오류 문구에 보여줌)


def describe_connection_error(exc, url):
    """requests 예외 -> 사람이 읽을 원인 (Render 에서 로컬 AI 에 못 닿는 흔한 경우들)."""
    host = requests.utils.urlparse(url).hostname or url
    text = str(exc)
    if isinstance(exc, requests.Timeout):
        return f"{host} 가 제한 시간 안에 응답하지 않습니다 (AI 컴퓨터가 바쁘거나 꺼져 있음)"
    if isinstance(exc, requests.exceptions.SSLError):
        return f"{host} 의 HTTPS 인증서를 확인하지 못했습니다"
    if isinstance(exc, requests.ConnectionError):
        if any(s in text for s in ("NameResolution", "Name or service not known", "getaddrinfo", "nodename nor servname")):
            return (f"{host} 주소를 인터넷에서 찾을 수 없습니다. Render 는 Tailscale 네트워크 밖이라 "
                    "Tailscale Funnel 로 공개해야 접속할 수 있습니다 (AI 컴퓨터에서 'tailscale funnel status' 확인)")
        if "refused" in text.lower():
            return f"{host} 가 연결을 거부했습니다 (Funnel 이 가리키는 포트에 AI 서버가 떠 있는지 확인)"
        return f"{host} 에 연결하지 못했습니다 ({text[:150]})"
    return text[:200]


def describe_http_error(response, url):
    host = requests.utils.urlparse(url).hostname or url
    if response.status_code in (401, 403):
        return (f"{host} 가 API 키를 거부했습니다 ({response.status_code}). Render 의 LOCALAI_API_KEY 값이 "
                "AI 컴퓨터 게이트웨이 .env 의 API_KEYS 에 들어 있는지 확인하고, .env 를 고쳤다면 게이트웨이를 다시 시작하세요")
    if response.status_code == 413:
        return (f"{host}: 보낸 글이 AI 서버의 입력 한도보다 깁니다 (413, 게이트웨이 .env 의 MAX_INPUT_CHARS 를 늘리거나 "
                "Render 의 LOCALAI_MAX_CHARS 를 줄이세요)")
    if response.status_code == 404:
        return f"{url} 주소가 없습니다 (404, LOCALAI_URL 경로 확인)"
    if response.status_code in (502, 503, 504) and not (response.text or "").strip():
        # 내용 없는 502 = Tailscale Funnel 은 켜져 있지만 그 뒤의 게이트웨이 프로그램이 꺼져 있음
        return (f"{host} 는 연결되지만 AI 컴퓨터의 게이트웨이 프로그램이 꺼져 있습니다 ({response.status_code}). "
                "AI 컴퓨터에서 localapi 의 scripts\\start_windows.bat 을 실행하세요")
    return f"{host} 응답 {response.status_code}: {response.text[:150]}"


def _model_ids(payload):
    """OpenAI 형식 {"data": [{"id"}]} 과 Ollama 형식 {"models": [{"name"}]} 모두."""
    items = (payload or {}).get("data") or (payload or {}).get("models") or []
    return [str(m.get("id") or m.get("model") or m.get("name")) for m in items
            if isinstance(m, dict) and (m.get("id") or m.get("model") or m.get("name"))]


def list_models(name):
    """서버에 올라와 있는 모델 이름들. 실패하면 (None, 원인)."""
    base = _base_url(name)
    urls = [f"{base}/models"]
    if base.endswith("/v1"):
        urls.append(base[:-3] + "/api/tags")        # Ollama 고유 주소 (OpenAI 형식 목록이 없을 때)
    reason = ""
    for url in urls:
        try:
            response = requests.get(url, headers=_headers(name), timeout=15)
        except requests.RequestException as exc:
            return None, describe_connection_error(exc, url)   # 연결 자체가 안 되면 다른 주소도 소용없음
        if response.status_code != 200:
            reason = describe_http_error(response, url)
            if response.status_code in (401, 403):
                return None, reason
            continue
        try:
            ids = _model_ids(response.json())
        except ValueError:
            reason = f"{url} 응답이 JSON 이 아닙니다 ({response.text[:80]!r})"
            continue
        if ids:
            return ids, ""
        reason = f"{url} 에 올라와 있는 모델이 없습니다"
    return None, reason


def _discover_model(name):
    """모델 이름을 정하지 않았으면 서버에 올라와 있는 첫 번째 모델."""
    if name in _discovered_models:
        return _discovered_models[name]
    ids, reason = list_models(name)
    if not ids:
        logger.warning("%s model discovery failed: %s", name, reason)
        _discovery_errors[name] = reason
        return ""
    _discovery_errors.pop(name, None)
    _discovered_models[name] = ids[0]
    return ids[0]


def no_model_message(name):
    conf = OPENAI_COMPATIBLE[name]
    reason = _discovery_errors.get(name) or "서버에서 모델 목록을 받지 못함"
    return f"{conf['label']} 에서 사용할 모델을 찾지 못했습니다: {reason}. (모델 이름을 {conf['models_setting']} 에 직접 적어도 됩니다)"


def _models(name):
    raw = getattr(settings, OPENAI_COMPATIBLE[name]["models_setting"], "") or ""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models and "url_setting" in OPENAI_COMPATIBLE[name]:
        found = _discover_model(name)
        models = [found] if found else []
    return models


def _parse_json_schedules(text):
    text = clean_content(text)
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


def split_chunks(text, max_lines):
    """로컬 AI 용: 긴 파일을 max_lines 줄씩 나눔. 첫 줄(열 이름/제목)은 조각마다 앞에 붙여 맥락 유지.
    빈 줄로 구분된 메모 형식이면 되도록 빈 줄에서 끊어 한 환자 기록이 둘로 갈리지 않게 함."""
    lines = text.splitlines()
    filled = [i for i, line in enumerate(lines) if line.strip()]
    if max_lines <= 0 or len(filled) <= max_lines + 1:
        return [text]
    header, rest = lines[filled[0]], lines[filled[0] + 1:]
    memo_style = any(not line.strip() for line in rest)
    chunks, current, count = [], [], 0
    for line in rest:
        current.append(line)
        if line.strip():
            count += 1
        at_break = not line.strip() if memo_style else True
        if count >= max_lines and (at_break or count >= max_lines * 3 // 2):
            chunks.append(current)
            current, count = [], 0
    if count:
        chunks.append(current)
    return ["\n".join([header, *chunk]).strip("\n") for chunk in chunks]


def _dedupe(records):
    seen, result = set(), []
    for record in records:
        key = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result


def _openai_compatible(name, source_text, filename, deadline, progress=None):
    """로컬 AI 는 한 번에 긴 JSON 을 만들면 느려 시간 초과가 나므로 파일을 조각내 차례로 요청."""
    chunks = split_chunks(source_text, settings.LOCALAI_CHUNK_LINES) if name == "localai" else [source_text]
    if len(chunks) == 1:
        return _request_schedules(name, source_text, filename, deadline)
    records = []
    for index, chunk in enumerate(chunks):
        if progress:
            progress(index, len(chunks))
        note = (f"{filename} - 전체 {len(chunks)}조각 중 {index + 1}번째. 첫 줄은 열 이름/제목(맥락용)이니 "
                "그 줄 자체가 일정이 아니면 일정으로 만들지 마세요")
        records.extend(_request_schedules(name, chunk, note, deadline, allow_empty=True))
    if not records:
        raise ScheduleExtractionError(f"{OPENAI_COMPATIBLE[name]['label']} 가 파일에서 일정을 찾지 못했습니다.")
    return _dedupe(records)


def _request_schedules(name, source_text, filename, deadline, allow_empty=False):
    conf = OPENAI_COMPATIBLE[name]
    messages = [{"role": "system", "content": JSON_INSTRUCTIONS}]
    for example in BASE_EXAMPLES:
        messages.append({"role": "user", "content": example["input"]})
        messages.append({"role": "assistant", "content": json.dumps({"schedules": example["output"]}, ensure_ascii=False)})
    messages.append({"role": "user", "content": f"--- 업로드된 파일 ({filename}) 내용 ---\n{source_text}"})

    failures = []
    models = _models(name)
    if not models:
        raise ScheduleExtractionError(no_model_message(name))
    for model in models:
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        try:
            response = _post_chat(name, model, messages, min(_timeout(name), remaining))
        except requests.Timeout:
            failures.append(f"{model}: 시간 초과" + (" - AI 컴퓨터가 너무 느립니다. 게이트웨이 .env 의 NUM_CTX 를 8192 로 "
                                                     "낮추거나(그래픽카드 메모리 부족 시 CPU 로 돌아 매우 느려짐) "
                                                     "Render 의 LOCALAI_CHUNK_LINES 를 줄여 보세요" if name == "localai" else ""))
            continue
        except requests.RequestException as exc:
            logger.warning("%s request failed: %s", name, exc)
            failures.append(f"{model}: {describe_connection_error(exc, _base_url(name))}")
            continue

        if response.status_code in (401, 403):
            raise ScheduleExtractionError(f"{conf['label']} API 키가 올바르지 않습니다 ({conf['key_setting']} 확인).")
        if response.status_code != 200:
            logger.warning("%s model %s returned %s: %s", name, model, response.status_code, response.text[:300])
            failures.append(f"{model}: {describe_http_error(response, f'{_base_url(name)}/chat/completions')}"
                            if name == "localai" else f"{model}: {response.status_code}")
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
        if schedules or allow_empty:
            return schedules
        failures.append(f"{model}: 일정 없음")
    raise ScheduleExtractionError(f"{conf['label']} 모델이 응답하지 않았습니다 ({'; '.join(failures) or '시간 부족'}).")


def extract_schedules(source_text, filename="", progress=None):
    """Tries each configured provider in order; returns the first non-empty result.
    progress(i, n): 로컬 AI 가 파일을 n 조각으로 나눠 i 번째를 시작할 때 불림 (화면 진행 표시용)."""
    if not source_text.strip():
        raise ScheduleExtractionError("파일에서 읽을 수 있는 내용이 없습니다.")
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ScheduleExtractionError("파일 내용이 너무 커서 처리할 수 없습니다. 파일을 나누어 업로드해주세요.")
    providers = configured_providers()
    if not providers:
        raise ScheduleExtractionError(
            "이 파일은 표(열 이름) 형식이 아니라 AI 분석이 필요한데, 서버에 AI 가 설정되어 있지 않습니다. "
            "LOCALAI_URL 과 LOCALAI_API_KEY 를 설정하거나, 날짜·방·시간·수술명·환자명 열이 있는 엑셀로 올려주세요."
        )

    budget = settings.LOCALAI_SCHEDULE_BUDGET if "localai" in providers else settings.SCHEDULE_AI_TIME_BUDGET
    deadline = time.monotonic() + budget
    errors = []
    for name in providers:
        if deadline - time.monotonic() < 5:
            break
        try:
            if name == "gemini":
                return gemini_client.extract_schedules_from_text(source_text, filename)
            return _openai_compatible(name, source_text, filename, deadline, progress)
        except ScheduleExtractionError as exc:
            logger.warning("AI provider %s failed: %s", name, exc)
            errors.append(str(exc))
    raise ScheduleExtractionError(
        (" / ".join(errors) or "AI 분석 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.") + _missing_key_hint())


# ---------- 작은 질문: 예상 수술 시간 열 찾기 ----------
# 표 형식 업로드에서 열 이름 규칙으로 예상 시간 열을 못 찾았을 때만, 남은 열 이름과 시간처럼 생긴
# 예시 값만 보내 묻는다 (환자 정보는 보내지 않음). 업로드 요청 안에서 기다리므로 짧게 끝낸다.
COLUMN_QUESTION_BUDGET_SECONDS = 30   # 로컬 AI 는 첫 응답이 느릴 수 있어 넉넉히
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
    models = _models(name)
    if not models:
        raise ValueError(no_model_message(name))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    try:
        response = _post_chat(name, models[0], messages, timeout)
    except requests.RequestException as exc:
        raise ValueError(describe_connection_error(exc, _base_url(name))) from exc
    if response.status_code != 200:
        raise ValueError(describe_http_error(response, f"{_base_url(name)}/chat/completions"))
    return clean_content(response.json()["choices"][0]["message"]["content"])


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
            parsed = json.loads(clean_content(text))
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
