from django import template
from django.utils.safestring import mark_safe

from board.forms import sanitize_post_html

register = template.Library()


@register.filter
def clean_html(value):
    """게시글 HTML 을 보여주기 직전에 한 번 더 정리 (새 편집기 이전에 저장된 글 포함)."""
    return mark_safe(sanitize_post_html(value))
