# chat/forms.py
from django import forms
from .models import ChatRoom

class ChatRoomForm(forms.ModelForm):
    class Meta:
        model = ChatRoom
        fields = ['name', 'password']
        widgets = {
            'password': forms.PasswordInput(),
        }
        labels = {
            'name': '방 제목',
            'password': '비밀번호 (선택사항)',
        }
