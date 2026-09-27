import re


ADSENSE_SCRIPT_PATTERN = re.compile(
    r'\s*<script[^>]*src="https://pagead2\.googlesyndication\.com/pagead/js/adsbygoogle\.js[^"]*"[^>]*></script>\s*',
    re.IGNORECASE,
)
ADSENSE_META_PATTERN = re.compile(
    r'\s*<meta[^>]+name=["\']google-adsense-account["\'][^>]*>\s*',
    re.IGNORECASE,
)


class RemoveGoogleAdSenseMiddleware:
    """Strips any injected Google AdSense snippets before the response is sent."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            getattr(response, "streaming", False)
            or "text/html" not in response.get("Content-Type", "")
            or not hasattr(response, "content")
        ):
            return response

        charset = getattr(response, "charset", "utf-8")
        try:
            content = response.content.decode(charset)
        except (UnicodeDecodeError, AttributeError):
            return response

        cleaned_content, script_removed = ADSENSE_SCRIPT_PATTERN.subn("", content)
        cleaned_content, meta_removed = ADSENSE_META_PATTERN.subn("", cleaned_content)

        if script_removed or meta_removed:
            response.content = cleaned_content.encode(charset)
            if response.has_header("Content-Length"):
                response["Content-Length"] = len(response.content)

        return response


# ---------------------------------------------------------------------------
# 방문자 수 세기
# ---------------------------------------------------------------------------

from django.core.cache import cache
from django.db.models import F, Sum
from django.utils import timezone

VISIT_COOKIE = "anx_visit"
VISIT_GAP_SECONDS = 30 * 60           # 30분 안에 다시 오면 같은 방문
VISIT_TOTAL_CACHE_KEY = "land:visit-totals"
_BOT_UA = re.compile(r"bot|crawl|spider|slurp|preview|monitor|uptime|curl|wget|python-requests|httpx|headless", re.I)
_SKIP_PREFIXES = ("/static/", "/admin/", "/api/", "/health", "/ckeditor5/", "/favicon")


def visit_totals():
    """(전체 방문 수, 오늘 방문 수) - 1분 캐시."""
    totals = cache.get(VISIT_TOTAL_CACHE_KEY)
    if totals is None:
        from land.models import DailyVisit

        today = timezone.localdate()
        total = DailyVisit.objects.aggregate(total=Sum("count"))["total"] or 0
        today_count = DailyVisit.objects.filter(date=today).values_list("count", flat=True).first() or 0
        totals = (total, today_count)
        cache.set(VISIT_TOTAL_CACHE_KEY, totals, 60)
    return totals


def record_visit(day=None):
    from land.models import DailyVisit

    day = day or timezone.localdate()
    DailyVisit.objects.get_or_create(date=day)
    DailyVisit.objects.filter(date=day).update(count=F("count") + 1)
    cache.delete(VISIT_TOTAL_CACHE_KEY)


class VisitCounterMiddleware:
    """사람이 여는 화면(HTML GET)만, 브라우저마다 30분 간격으로 한 번 센다.
    쿠키만 쓰므로 로그인·세션과 무관하고 개인 정보는 저장하지 않는다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method != "GET"
            or response.status_code != 200
            or "text/html" not in response.get("Content-Type", "")
            or request.path.startswith(_SKIP_PREFIXES)
            or _BOT_UA.search(request.META.get("HTTP_USER_AGENT", "") or "bot")
        ):
            return response
        if VISIT_COOKIE not in request.COOKIES:
            try:
                record_visit()
            except Exception:
                return response      # 방문 수 때문에 화면이 깨지면 안 됨
        # 머무는 동안은 계속 연장 (30분 동안 조용하면 다음 접속을 새 방문으로)
        response.set_cookie(VISIT_COOKIE, "1", max_age=VISIT_GAP_SECONDS, httponly=True,
                            samesite="Lax", secure=request.is_secure())
        return response
