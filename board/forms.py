# board/forms.py

from django import forms
from .models import Board, Comment
from ckeditor.widgets import CKEditorWidget

class BoardForm(forms.ModelForm):
    contents = forms.CharField(widget=CKEditorWidget())

    class Meta:
        model = Board
        fields = ['title', 'contents']

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            # 아래 'class' 속성을 추가했습니다.
            'content': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 4, # rows는 3에서 4로 조금 늘려 더 나은 사용자 경험을 제공합니다.
                'placeholder': '따뜻한 댓글을 남겨주세요...' # 플레이스홀더 텍스트를 수정했습니다.
            }),
        }
        # label이 필요 없다면 아래 코드를 추가하여 숨길 수 있습니다.
        labels = {
            'content': '',
        }