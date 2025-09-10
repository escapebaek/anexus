# board/forms.py

from django import forms
from .models import Board, Comment
from ckeditor.widgets import CKEditorWidget

class BoardForm(forms.ModelForm):
    contents = forms.CharField(widget=CKEditorWidget())

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