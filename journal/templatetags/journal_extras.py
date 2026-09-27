import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def summary_html(text):
    """AI 요약 -> HTML. '### 항목' 줄은 항목 제목으로, 나머지는 문단으로 (예전 문단식 요약도 그대로 표시)."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [line.rstrip() for line in block.strip().splitlines()]
        if lines and lines[0].startswith("#"):
            out.append(f'<h4 class="summary-heading">{escape(lines[0].lstrip("#").strip())}</h4>')
            lines = lines[1:]
        if lines:
            out.append("<p>" + "<br>".join(escape(line) for line in lines) + "</p>")
    return mark_safe("".join(out))
