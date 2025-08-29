import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(name='mdtohtml')
def mdtohtml(value):
    """마크다운을 HTML로 변환"""
    if not value:
        return ''
    
    md = markdown.Markdown(
        extensions=[
            'markdown.extensions.extra',      # 테이블, 각주 등 추가 기능
            'markdown.extensions.codehilite', # 코드 하이라이팅
            'markdown.extensions.toc',        # 목차 생성
            'markdown.extensions.nl2br',      # 줄바꿈을 <br>로 변환
        ],
        extension_configs={
            'markdown.extensions.codehilite': {
                'css_class': 'highlight',
                'use_pygments': False,  # CSS로 스타일링
            }
        }
    )
    
    html = md.convert(value)
    return mark_safe(html)