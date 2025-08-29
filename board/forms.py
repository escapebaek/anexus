from django import forms
from .models import Board, Comment
from mdeditor.fields import MDTextFormField

class BoardForm(forms.ModelForm):
    contents = MDTextFormField()  # CKEditorWidget 대신 사용

    class Meta:
        model = Board
        fields = ['title', 'contents']

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