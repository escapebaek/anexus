"""논문 자동 처리: 올린 PDF 한 편마다
1) PDF 앞부분 글자에서 DOI 를 찾아 Crossref(무료 논문 정보 DB)로 정확한 제목·저자를 가져오고
2) AI 로 한국어 요약(한 줄 요약 + 항목별 요약)을 만든다.

AI 는 Gemini 를 먼저 쓴다 (PDF 를 통째로 읽어 표·그림 설명까지 반영). Gemini 가 안 되면
PDF 에서 뽑은 글자로 Groq 등 다른 무료 제공자에게 묻는다. 모두 실패하면 '오류' 로 남기고
화면의 '다시 시도' 로 재처리한다.

처리는 백그라운드 스레드 하나가 대기 중인 논문을 한 편씩 차례로 가져가 처리한다 (무료 AI 한도 보호).
여러 gunicorn 워커가 동시에 돌아도 DB 에서 '대기 → 처리 중' 으로 바꾸는 데 성공한 쪽만 처리한다.
"""
import base64
import io
import json
import logging
import re
import threading
from datetime import timedelta

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
    pass


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


def crossref_metadata(doi):
    """DOI -> {'title', 'authors'} (Crossref). 실패하면 None."""
    if not doi:
        return None
    try:
        res = requests.get(CROSSREF_URL.format(doi=doi), timeout=12,
                           headers={"User-Agent": "ANExuS journal stand (https://anexus.cloud)"})
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
    return {"title": title, "authors": authors}


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


def _gemini_summary(pdf_bytes, text):
    if not settings.GEMINI_API_KEY:
        raise ProcessingError("Gemini 키 없음")
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
    response = gemini_client._post_with_fallback(settings.GEMINI_API_KEY, payload)
    try:
        return _parse_summary(response.json()["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProcessingError(f"Gemini 응답을 해석하지 못했습니다 ({exc})") from exc


def _text_provider_summary(text):
    """Gemini 가 안 될 때: PDF 글자로 다른 무료 제공자에게."""
    if not text.strip():
        raise ProcessingError("PDF 에서 글자를 읽을 수 없어 다른 AI 로 요약할 수 없습니다")
    prompt = ("논문 본문:\n" + text[:MAX_TEXT_CHARS_SMALL]
              + '\n\nJSON 형식: {"title": "", "authors": "", "doi": "", "short_summary": "", '
                '"sections": [{"heading": "", "body": ""}]}')
    errors = []
    for name in ai_client.configured_providers():
        if name == "gemini":
            continue
        try:
            raw = ai_client._ask_openai_compatible_json(name, SYSTEM_PROMPT, prompt, 120)
            return _parse_summary(raw)
        except Exception as exc:
            logger.warning("summary via %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}"[:200])
    raise ProcessingError("다른 AI 제공자도 실패했습니다 " + "; ".join(errors))


def summarize(pdf_bytes, text):
    try:
        return _gemini_summary(pdf_bytes, text)
    except Exception as exc:
        logger.warning("Gemini summary failed, trying text providers: %s", exc)
        first_error = str(exc)
    try:
        return _text_provider_summary(text)
    except ProcessingError as exc:
        raise ProcessingError(f"요약 실패 - Gemini: {first_error[:300]} / {exc}") from exc


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


def _claim_next():
    now = timezone.now()
    Paper.objects.filter(processing_status="running", processing_updated__lt=now - STALE_AFTER) \
        .update(processing_status="pending")
    for pid in Paper.objects.filter(processing_status="pending").order_by("issue_id", "order", "id") \
            .values_list("id", flat=True)[:10]:
        if Paper.objects.filter(id=pid, processing_status="pending") \
                .update(processing_status="running", processing_updated=now):
            return Paper.objects.get(id=pid)
    return None


def run_pending():
    """대기 중인 논문을 모두 처리 (한 편씩)."""
    while True:
        paper = _claim_next()
        if paper is None:
            return
        try:
            process_paper(paper)
        except Exception as exc:
            if isinstance(exc, ProcessingError):
                logger.warning("paper %s processing failed: %s", paper.pk, exc)
            else:
                logger.exception("paper %s processing failed", paper.pk)
            Paper.objects.filter(pk=paper.pk).update(
                processing_status="error", processing_message=str(exc)[:1000], processing_updated=timezone.now())


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
                    # 끝내기 직전에 새로 올라온 논문이 있으면 이어서 처리
                    with _worker_lock:
                        if not Paper.objects.filter(processing_status="pending").exists():
                            _worker_thread = None
                            return
            finally:
                connection.close()

        _worker_thread = threading.Thread(target=target, daemon=True, name="journal-processing")
        _worker_thread.start()
