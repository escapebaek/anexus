# exam/templatetags/markdown_extras.py

from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape
import re

register = template.Library()

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

@register.filter(name='markdown', is_safe=True)
def markdown_format(text):
    """
    Markdown 텍스트를 HTML로 변환하는 필터
    markdown 라이브러리가 없으면 기본 텍스트 포맷팅 적용
    """
    if not text:
        return ""
    
    # 입력값이 문자열이 아닐 경우 문자열로 변환
    if not isinstance(text, str):
        text = str(text)
    
    if MARKDOWN_AVAILABLE:
        try:
            # Markdown 확장 기능들을 포함하여 변환
            md = markdown.Markdown(extensions=[
                'markdown.extensions.extra',      # 테이블, 코드블록 등
                'markdown.extensions.nl2br',      # 줄바꿈을 <br>로 변환
                'markdown.extensions.tables',     # 테이블 지원
                'markdown.extensions.fenced_code',  # 코드 블록 지원
            ], extension_configs={
                'markdown.extensions.extra': {},
                'markdown.extensions.nl2br': {},
            })
            
            html = md.convert(text)
            return mark_safe(html)
        except Exception as e:
            # markdown 처리 중 오류 발생 시 기본 포맷팅 사용
            print(f"Markdown conversion error: {e}")
            return basic_text_format(text)
    else:
        # markdown 라이브러리가 없으면 기본 텍스트 포맷팅 사용
        return basic_text_format(text)

def basic_text_format(text):
    """
    Markdown이 없을 때 기본적인 텍스트 포맷팅
    """
    if not text:
        return ""
    
    # HTML 이스케이프 처리
    html = escape(text)
    
    # 기본적인 마크다운 문법을 HTML로 변환
    
    # 코드 블록 처리 (```로 둘러싸인 부분)
    html = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', html, flags=re.DOTALL)
    
    # 인라인 코드 `코드` -> <code>코드</code>
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # 굵은 글씨 **텍스트** -> <strong>텍스트</strong>
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html, flags=re.DOTALL)
    
    # 기울임 *텍스트* -> <em>텍스트</em>
    html = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', html)
    
    # 제목 처리
    html = re.sub(r'^#### (.*?)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    
    # 줄바꿈 처리
    html = re.sub(r'\n\n+', '</p><p>', html)
    html = re.sub(r'\n', '<br>', html)
    
    # 단락으로 감싸기
    if not html.startswith('<'):
        html = '<p>' + html + '</p>'
    
    # 리스트 처리
    html = process_lists(html)
    
    return mark_safe(html)

def process_lists(html):
    """
    리스트 처리 함수
    """
    lines = html.split('<br>')
    result_lines = []
    in_list = False
    
    for line in lines:
        line = line.strip()
        if re.match(r'^\s*[-*+]\s+', line):
            if not in_list:
                result_lines.append('<ul>')
                in_list = True
            item_text = re.sub(r'^\s*[-*+]\s+', '', line)
            result_lines.append(f'<li>{item_text}</li>')
        else:
            if in_list:
                result_lines.append('</ul>')
                in_list = False
            if line:  # 빈 줄이 아닐 때만 추가
                result_lines.append(line)
    
    if in_list:
        result_lines.append('</ul>')
    
    return '<br>'.join(result_lines)

@register.filter(name='safe_markdown', is_safe=True)
def safe_markdown(text):
    """
    안전한 Markdown 변환 (XSS 방지 포함)
    """
    if not text:
        return ""
    
    # markdown_format 필터를 사용하되, 추가적인 보안 처리
    html = markdown_format(text)
    
    # XSS 방지를 위한 기본적인 정화
    if isinstance(html, str):
        # script 태그 제거
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<iframe[^>]*>.*?</iframe>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # 이벤트 핸들러 제거
        html = re.sub(r'on\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
    
    return mark_safe(html)