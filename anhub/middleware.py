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
