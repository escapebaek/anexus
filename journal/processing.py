"""논문 자동 처리: 올린 PDF 한 편마다
1) PDF 앞부분 글자에서 DOI 를 찾아 Crossref(무료 논문 정보 DB)로 정확한 제목·저자·권·호·발행일을 가져오고
   (권·호·발행일은 올릴 때 바로 써서 맞는 호에 넣음 - views.upload_file)
2) Gemini(무료 API)가 PDF 를 통째로 읽고 한국어 요약(한 줄 요약 + 항목별 요약)을 만든다.

무료 한도: 모델마다 따로라 한도에 걸리면 다음 모델로 넘어가고, 모두 막히면 '대기' 로 두고 나중에 다시 시도한다.
  - 분당 한도(RPM·TPM): 1분 남짓 뒤 (Google 이 알려준 retryDelay 를 따름)
  - 하루 한도(RPD): Google 이 하루 한도를 초기화하는 미국 태평양 시각 자정 직후 (한국 시각 오후 4~5시)
  - 종류를 알 수 없으면 3시간 뒤
  과부하(503)·시간 초과는 15분 뒤. PDF 를 읽을 수 없는 등 다시 해도 안 되는 경우만 '오류'.

처리는 백그라운드 스레드 하나가 '지금 시도할 차례인' 대기 논문을 한 편씩 차례로 처리한다.
Render 무료 서버는 접속이 없으면 잠들어 스레드도 멈추므로, GitHub Actions 가 30분마다
/journal/process-tick/ 을 불러 서버를 깨우고 남은 논문을 이어서 처리한다 (.github/workflows/journal-tick.yml).
여러 gunicorn 워커가 동시에 돌아도 DB 에서 '대기 → 처리 중' 으로 바꾸는 데 성공한 쪽만 처리한다.
"""
import base64
import io
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.db import connection
from django.utils import timezone

from schedule import ai_client, gemini_client

from .models import Paper

logger = logging.getLogger(__name__)

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
MAX_INLINE_PDF_BYTES = 15 * 1024 * 1024     # Gemini 요청 한도(20MB) 안쪽
MAX_TEXT_CHARS = 60_000                     # 글자로 보낼 때 (Gemini)
MAX_TEXT_CHARS_SMALL = 24_000               # 분당 토큰 한도가 작은 무료 제공자용
STALE_AFTER = timedelta(minutes=12)         # 이보다 오래 '처리 중' 이면 서버 재시작 등으로 끊긴 것
GEMINI_TIMEOUT = 180                        # 요청 하나 (PDF 를 읽어 요약하는 데 1분 넘게 걸리기도 함)
GAP_BETWEEN_PAPERS = 5                      # 초. 무료 분당 요청 한도 보호 (논문 사이 쉬는 시간)
WAIT_SOON = timedelta(minutes=5)            # 다음 시도가 이 안이면 스레드가 기다렸다 이어서 처리
RETRY_OVERLOAD = timedelta(minutes=15)      # 과부하·시간 초과
RETRY_UNKNOWN_QUOTA = timedelta(hours=3)    # 어떤 한도인지 모를 때
QUOTA_TZ = ZoneInfo("America/Los_Angeles")  # Gemini 하루 한도가 초기화되는 시간대 (자정)

SECTION_GUIDE = "연구 목적, 연구 방법, 주요 결과, 임상적 의미"

SYSTEM_PROMPT = f"""당신은 마취통증의학과 전문의를 위한 학술 논문 요약가입니다.
첨부한 논문을 읽고 한국어로 요약해 JSON 으로만 답하세요.

- title: 논문의 영어 제목 그대로
- authors: 저자 이름을 쉼표로 구분 (6명이 넘으면 앞 6명 뒤에 ", et al.")
- doi: 논문에 적힌 DOI (없으면 빈 문자열)
- short_summary: 논문의 핵심을 담은 한국어 한 문장 (120자 안팎)
- sections: 항목별 요약. 연구 논문이면 [{SECTION_GUIDE}] 4개 항목으로,
  종설·사설·가이드라인 등은 성격에 맞게 3~4개 항목(예: 배경, 핵심 내용, 시사점)으로.
  각 항목은 2~4문장, 전체 합쳐 900~1,300자 정도로 간결하게.

주의: 표본 수, 주요 결과 수치, 효과 크기, P 값·신뢰구간은 원문 그대로 정확히 쓰세요.
원문에 없는 내용을 추측해 넣지 마세요. 의학 용어는 필요하면 한국어(영어)로 병기하세요."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "authors": {"type": "STRING"},
        "doi": {"type": "STRING"},
        "short_summary": {"type": "STRING"},
        "sections": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"}},
                "required": ["heading", "body"],
            },
        },
    },
    "required": ["title", "short_summary", "sections"],
}


class ProcessingError(Exception):
    """다시 해도 안 되는 실패 (PDF 를 읽을 수 없음, API 키 오류 등) → '오류'."""


class RetryLater(Exception):
    """잠시 뒤 다시 하면 될 실패 (무료 한도, 과부하) → '대기' 로 두고 wait 뒤에 다시."""

    def __init__(self, wait, message):
        super().__init__(message)
        self.wait = wait


# ---------------------------------------------------------------------------
# PDF · DOI · Crossref
# ---------------------------------------------------------------------------
def extract_text(pdf_bytes, max_pages=None):
    """PDF 글자 (스캔 이미지 PDF 는 빈 문자열일 수 있음)."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = reader.pages if max_pages is None else reader.pages[:max_pages]
        return "\n".join((page.extract_text() or "") for page in pages)
    except Exception as exc:        # 깨진 PDF 등 - 요약은 Gemini 가 PDF 로 직접 시도
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def find_doi(text):
    match = DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(1).rstrip(".,;)]}").rstrip("'")


def _crossref_date(item):
    """인쇄 발행일 → 발행일 → 온라인 발행일 순. 연·월만 있으면 1일로."""
    for key in ("published-print", "issued", "published-online", "published"):
        parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            try:
                return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1)
            except (TypeError, ValueError):
                continue
    return None


def crossref_metadata(doi):
    """DOI -> {'title', 'authors', 'volume', 'issue', 'date', 'journal'} (Crossref). 실패하면 None.
    volume·issue 는 온라인 선공개(아직 호에 실리지 않은) 논문이면 빈 문자열."""
    if not doi:
        return None
    try:
        res = requests.get(CROSSREF_URL.format(doi=doi), timeout=12,
                           headers={"User-Agent": "ANExUS journal stand (https://anexus.live)"})
        if res.status_code != 200:
            return None
        item = res.json().get("message") or {}
    except (requests.RequestException, ValueError):
        return None
    title = " ".join((item.get("title") or [""])[0].split())
    names = []
    for person in item.get("author") or []:
        name = " ".join(p for p in (person.get("given"), person.get("family")) if p) or person.get("name", "")
        if name:
            names.append(name)
    authors = ", ".join(names[:6]) + (", et al." if len(names) > 6 else "")
    if not title:
        return None
    return {
        "title": title,
        "authors": authors,
        "volume": str(item.get("volume") or "").strip()[:50],
        "issue": str(item.get("issue") or "").strip()[:50],
        "date": _crossref_date(item),
        "journal": " ".join(((item.get("container-title") or [""])[0]).split()),
    }


def pdf_metadata(pdf_bytes):
    """올릴 때 바로 쓰는 정보: PDF 앞 두 쪽의 DOI → Crossref. (doi, meta 또는 None)"""
    doi = find_doi(extract_text(pdf_bytes, max_pages=2))
    return doi, crossref_metadata(doi)


# ---------------------------------------------------------------------------
# AI 요약
# ---------------------------------------------------------------------------
def _parse_summary(raw):
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    data = json.loads(fenced.group(1) if fenced else text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    sections = [s for s in data.get("sections") or []
                if isinstance(s, dict) and str(s.get("body") or "").strip()]
    if not sections or not str(data.get("short_summary") or "").strip():
        raise ValueError("empty summary")
    data["sections"] = sections
    return data


def _seconds_until_quota_reset(now=None):
    """Gemini 하루 한도가 초기화되는 다음 태평양 시각 자정(+5분 여유)까지 남은 초."""
    now = (now or timezone.now()).astimezone(QUOTA_TZ)
    reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=QUOTA_TZ) + timedelta(minutes=5)
    return max(60, int((reset - now).total_seconds()))


def quota_wait(response, now=None):
    """429 응답 → 다시 시도까지 기다릴 시간(timedelta). 하루 한도면 초기화 시각까지,
    분당 한도면 Google 이 알려준 retryDelay(최소 1분), 알 수 없으면 3시간."""
    try:
        details = (response.json().get("error") or {}).get("details") or []
    except ValueError:
        details = []
    quota_ids, retry_delay = [], None
    for d in details:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations") or []:
            quota_ids.append(str((v or {}).get("quotaId") or ""))
        m = re.fullmatch(r"([\d.]+)s", str(d.get("retryDelay") or ""))
        if m:
            retry_delay = float(m.group(1))
    if any("PerDay" in q for q in quota_ids):
        return timedelta(seconds=_seconds_until_quota_reset(now))
    if any("PerMinute" in q for q in quota_ids) or retry_delay is not None:
        return timedelta(seconds=max(60, int((retry_delay or 0) + 15)))
    return RETRY_UNKNOWN_QUOTA


def journal_models():
    """논문 요약에 쓸 모델 순서: JOURNAL_GEMINI_MODEL(기본 gemini-4-hydrogen) → GEMINI_MODEL → 대체 모델들."""
    from schedule.gemini_client import model_chain

    chain = []
    for name in [settings.JOURNAL_GEMINI_MODEL] + model_chain():
        if name and name not in chain:
            chain.append(name)
    return chain


def _payload_for(model, payload):
    """Gemini 3·4 계열에만 생각 수준(thinkingLevel)을 붙임 (2.5 계열은 이 설정을 모름)."""
    level = settings.JOURNAL_GEMINI_THINKING
    if not level or not re.match(r"gemini-[34]", model):
        return payload
    config = dict(payload.get("generationConfig") or {}, thinkingConfig={"thinkingLevel": level})
    return dict(payload, generationConfig=config)


def _gemini_post(payload):
    """설정한 모델부터 차례로 (모델마다 무료 한도가 따로). 성공한 응답을 돌려주고,
    모두 한도·과부하로 막히면 RetryLater, 키 오류 등은 ProcessingError."""
    from schedule.gemini_client import GEMINI_ENDPOINT

    waits, problems = [], []
    for model in journal_models():
        try:
            response = requests.post(GEMINI_ENDPOINT.format(model=model), params={"key": settings.GEMINI_API_KEY},
                                     json=_payload_for(model, payload), timeout=GEMINI_TIMEOUT)
        except requests.Timeout:
            problems.append(f"{model}: 시간 초과")
            continue
        except requests.RequestException as exc:
            raise RetryLater(RETRY_OVERLOAD, f"Gemini 에 연결하지 못했습니다 ({exc.__class__.__name__})") from exc
        if response.status_code == 200:
            return response
        text = response.text[:300]
        logger.warning("Gemini %s for paper summary: %s %s", model, response.status_code, text)
        if response.status_code == 429:
            waits.append(quota_wait(response))
            problems.append(f"{model}: 무료 한도 초과")
        elif response.status_code in (500, 502, 503, 504):
            problems.append(f"{model}: 과부하({response.status_code})")
        elif response.status_code == 404 or (response.status_code == 400 and ("model" in text.lower() or "thinking" in text.lower())):
            problems.append(f"{model}: 사용할 수 없는 모델")
        elif response.status_code in (401, 403) or (response.status_code == 400 and "api key" in text.lower()):
            raise ProcessingError("Gemini API 키가 올바르지 않습니다 (Render 의 GEMINI_API_KEY 확인)")
        else:
            raise ProcessingError(f"Gemini 오류 {response.status_code}: {text[:200]}")
    if waits and len(waits) == len(problems):
        raise RetryLater(min(waits), "Gemini 무료 한도 초과 (" + ", ".join(problems) + ")")
    if waits:
        # 일부는 한도, 일부는 과부하 → 둘 중 먼저 풀릴 쪽에 맞춤
        raise RetryLater(min(min(waits), RETRY_OVERLOAD), "Gemini 한도·과부하 (" + ", ".join(problems) + ")")
    raise RetryLater(RETRY_OVERLOAD, "Gemini 가 응답하지 않습니다 (" + ", ".join(problems) + ")")


def _gemini_summary(pdf_bytes, text):
    if not settings.GEMINI_API_KEY:
        raise ProcessingError("서버에 Gemini API 키가 없습니다 (Render 환경변수 GEMINI_API_KEY)")
    if len(pdf_bytes) <= MAX_INLINE_PDF_BYTES:
        part = {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode()}}
    elif text.strip():
        part = {"text": text[:MAX_TEXT_CHARS]}
    else:
        raise ProcessingError("PDF 가 너무 크고 글자를 읽을 수 없습니다")
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [part, {"text": "이 논문을 위 형식으로 요약해 주세요."}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": RESPONSE_SCHEMA,
                             "temperature": 0.2},
    }
    response = _gemini_post(payload)
    try:
        # 생각 요약(thought) 조각이 섞여 와도 답 부분만
        parts = response.json()["candidates"][0]["content"]["parts"]
        answer = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return _parse_summary(answer)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # 내용 거부·빈 응답 등: 같은 PDF 로 다시 해도 같을 가능성이 커서 오류로 (화면의 '다시 시도' 로 재요청)
        raise ProcessingError(f"Gemini 응답을 해석하지 못했습니다 ({exc})") from exc


def _text_provider_summary(text):
    """PDF 에서 뽑은 글자로 요약 (지금은 로컬 AI. 예전에는 Gemini 가 안 될 때 Groq 등)."""
    if not text.strip():
        raise ProcessingError("PDF 에서 글자를 읽을 수 없습니다 (스캔 이미지 PDF 는 AI 가 읽을 수 없음)")
    providers = [name for name in ai_client.configured_providers() if name != "gemini"]
    if not providers:
        raise ProcessingError("서버에 AI 가 설정되어 있지 않습니다 (LOCALAI_URL, LOCALAI_API_KEY 확인)")
    max_chars = settings.LOCALAI_MAX_CHARS if providers[0] == "localai" else MAX_TEXT_CHARS_SMALL
    prompt = ("논문 본문:\n" + text[:max_chars]
              + '\n\nJSON 형식: {"title": "", "authors": "", "doi": "", "short_summary": "", '
                '"sections": [{"heading": "", "body": ""}]}')
    errors = []
    for name in providers:
        try:
            raw = ai_client._ask_openai_compatible_json(name, SYSTEM_PROMPT, prompt, ai_client._timeout(name, 120))
            return _parse_summary(raw)
        except Exception as exc:
            logger.warning("summary via %s failed: %s", name, exc)
            errors.append(f"{ai_client.OPENAI_COMPATIBLE[name]['label']}: {exc}"[:300])
    raise ProcessingError("요약 실패 - " + "; ".join(errors))


def summarize(pdf_bytes, text):
    """Gemini 가 PDF 를 통째로 읽어 요약 (로컬 AI 는 더 쓰지 않음 - _text_provider_summary 는 참고용으로 남김)."""
    return _gemini_summary(pdf_bytes, text)


def format_sections(sections):
    """[{heading, body}] -> '### 제목\\n내용\\n\\n### ...' (화면에서 항목 제목으로 표시)."""
    blocks = []
    for section in sections:
        heading = " ".join(str(section.get("heading") or "").split()).lstrip("#").strip()
        body = str(section.get("body") or "").strip()
        blocks.append(f"### {heading}\n{body}" if heading else body)
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# 한 편 처리 + 백그라운드 작업
# ---------------------------------------------------------------------------
def process_paper(paper):
    with paper.pdf_file.open("rb") as fh:
        pdf_bytes = fh.read()
    text = extract_text(pdf_bytes)

    # DOI 는 보통 첫 페이지에 있다 (참고문헌의 다른 논문 DOI 를 잡지 않도록 앞부분만)
    doi = paper.doi or find_doi(extract_text(pdf_bytes, max_pages=2))
    meta = crossref_metadata(doi)
    summary = summarize(pdf_bytes, text)

    doi = doi or find_doi(summary.get("doi", ""))
    if not meta and doi:
        meta = crossref_metadata(doi)
    paper.doi = doi[:255]
    paper.title = ((meta or {}).get("title") or str(summary.get("title") or "").strip() or paper.title)[:500]
    paper.authors = ((meta or {}).get("authors") or str(summary.get("authors") or "").strip() or paper.authors)[:500]
    paper.short_summary = " ".join(str(summary["short_summary"]).split())[:300]
    paper.ai_summary = format_sections(summary["sections"])
    paper.processing_status = ""
    paper.processing_message = "Crossref 에서 제목·저자를 가져왔습니다." if meta else "제목·저자는 AI 가 PDF 에서 읽었습니다."
    paper.processing_updated = timezone.now()
    paper.save()


def _due_pending(now):
    from django.db.models import Q
    return Paper.objects.filter(processing_status="pending").filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))


def _claim_next():
    now = timezone.now()
    Paper.objects.filter(processing_status="running", processing_updated__lt=now - STALE_AFTER) \
        .update(processing_status="pending")
    for pid in _due_pending(now).order_by("next_attempt_at", "issue_id", "order", "id") \
            .values_list("id", flat=True)[:10]:
        if Paper.objects.filter(id=pid, processing_status="pending") \
                .update(processing_status="running", processing_updated=now):
            return Paper.objects.get(id=pid)
    return None


def next_due_at():
    """아직 때가 안 된 대기 논문 중 가장 이른 다음 시도 시각 (없으면 None)."""
    return Paper.objects.filter(processing_status="pending", next_attempt_at__gt=timezone.now()) \
        .order_by("next_attempt_at").values_list("next_attempt_at", flat=True).first()


def run_pending():
    """지금 시도할 차례인 대기 논문을 모두 처리 (한 편씩, 사이에 잠깐 쉼).
    무료 한도에 걸리면 그 시각까지 다른 논문도 같은 한도라 모두 미룸."""
    while True:
        paper = _claim_next()
        if paper is None:
            return
        paper.attempts += 1      # process_paper 가 paper.save() 하므로 객체 값도 올려 둠
        Paper.objects.filter(pk=paper.pk).update(attempts=paper.attempts)
        try:
            process_paper(paper)
            Paper.objects.filter(pk=paper.pk).update(next_attempt_at=None)
        except RetryLater as exc:
            when = timezone.now() + exc.wait
            logger.info("paper %s: retry at %s (%s)", paper.pk, when, exc)
            local = timezone.localtime(when)
            Paper.objects.filter(pk=paper.pk).update(
                processing_status="pending", next_attempt_at=when, processing_updated=timezone.now(),
                processing_message=f"{exc} - {local:%m/%d %H:%M} 이후 자동으로 다시 시도")
            # 같은 한도를 쓰는 나머지 대기 논문도 그때까지 미룸 (헛되이 한도를 두드리지 않게)
            _due_pending(timezone.now()).update(
                next_attempt_at=when, processing_message=f"Gemini 한도 대기 - {local:%m/%d %H:%M} 이후 자동으로 처리")
            return
        except Exception as exc:
            if isinstance(exc, ProcessingError):
                logger.warning("paper %s processing failed: %s", paper.pk, exc)
            else:
                logger.exception("paper %s processing failed", paper.pk)
            Paper.objects.filter(pk=paper.pk).update(
                processing_status="error", processing_message=str(exc)[:1000], processing_updated=timezone.now(),
                next_attempt_at=None)
        time.sleep(GAP_BETWEEN_PAPERS)


_worker_lock = threading.Lock()
_worker_thread = None


def start_worker():
    """백그라운드 처리 시작 (이미 돌고 있으면 그대로 둠)."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return

        def target():
            global _worker_thread
            try:
                while True:
                    run_pending()
                    # 끝내기 직전에 새로 올라온(또는 곧 다시 시도할) 논문이 있으면 이어서 처리.
                    # 몇 시간 뒤에 다시 할 것은 스레드를 끝내고 GitHub Actions 의 깨우기(process-tick)에 맡김
                    with _worker_lock:
                        if _due_pending(timezone.now()).exists():
                            continue
                        upcoming = next_due_at()
                        if upcoming is None or upcoming - timezone.now() > WAIT_SOON:
                            _worker_thread = None
                            return
                    time.sleep(max(1, (upcoming - timezone.now()).total_seconds()))
            finally:
                connection.close()

        _worker_thread = threading.Thread(target=target, daemon=True, name="journal-processing")
        _worker_thread.start()
