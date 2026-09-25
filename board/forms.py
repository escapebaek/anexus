# board/forms.py

import re

import nh3
from django import forms
from .models import Board, Comment

# 게시글 본문으로 허용하는 HTML (Quill 편집기 출력 + 예전 CKEditor 글에 쓰인 태그)
ALLOWED_TAGS = {
    "p", "br", "span", "div", "strong", "b", "em", "i", "u", "s", "strike", "sub", "sup", "mark",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "hr",
    "ul", "ol", "li", "a", "img", "figure", "figcaption",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "colgroup", "col",
}
ALLOWED_ATTRIBUTES = {
    "*": {"style", "class"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "li": {"data-list"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "ol": {"start"},
}
ALLOWED_STYLES = {"color", "background-color", "text-align", "width", "height"}


def sanitize_post_html(html):
    """게시글 HTML 에서 스크립트·이벤트 속성·위험한 링크 등을 제거 (|safe 로 그대로 보여주므로 필수)."""
    return nh3.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        filter_style_properties=ALLOWED_STYLES,
        link_rel="noopener noreferrer",
    )


def html_is_blank(html):
    text = re.sub(r"<[^>]+>|&nbsp;|\s", "", html or "")
    return not text and "<img" not in (html or "")


class BoardForm(forms.ModelForm):
    # 화면에서는 Quill 편집기가 이 숨은 칸에 HTML 을 채워 넣음 (board_form.html)
    contents = forms.CharField(label="내용", widget=forms.Textarea(attrs={"class": "d-none", "id": "id_contents"}), required=False)

    class Meta:
        model = Board
        fields = ['title', 'contents', 'is_notice']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '제목을 입력하세요'
            }),
            'is_notice': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        labels = {
            'title': '제목',
            'contents': '내용',
            'is_notice': '공지사항으로 등록'
        }

    def clean_contents(self):
        html = sanitize_post_html(self.cleaned_data.get("contents"))
        if html_is_blank(html):
            raise forms.ValidationError("내용을 입력하세요.")
        return html

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # 관리자가 아닌 경우 공지사항 체크박스 숨기기
        if self.user and not (self.user.is_staff or self.user.is_superuser):
            self.fields['is_notice'].widget = forms.HiddenInput()
            self.fields['is_notice'].initial = False

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 4,
                'placeholder': '따뜻한 댓글을 남겨주세요...'
            }),
        }
        labels = {
            'content': '',
        }