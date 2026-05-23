from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email', 'real_name', 'training_hospital')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['real_name'].required = True
        self.fields['real_name'].label = '실명'