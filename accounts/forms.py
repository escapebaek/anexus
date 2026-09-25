from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm

from .models import CustomUser

# 예전에 가입할 때 넣던 임시 주소 — 실제 메일함이 아니므로 새로 쓰지 못하게 하고, 비밀번호 찾기에서도 뺀다
PLACEHOLDER_EMAILS = {'default@default.com', 'test@test.com'}
EMAIL_REQUIRED = '이메일을 입력해 주세요. 비밀번호를 찾을 때 필요합니다.'


def has_real_email(user):
    email = (user.email or '').strip().lower()
    return bool(email) and email not in PLACEHOLDER_EMAILS


def clean_unique_email(email, exclude_user=None):
    email = (email or '').strip()
    if not email:
        raise forms.ValidationError(EMAIL_REQUIRED)
    if email.lower() in PLACEHOLDER_EMAILS:
        raise forms.ValidationError('실제로 쓰는 이메일 주소를 입력해 주세요.')
    others = CustomUser.objects.filter(email__iexact=email)
    if exclude_user is not None:
        others = others.exclude(pk=exclude_user.pk)
    if others.exists():
        raise forms.ValidationError('이미 다른 계정에서 쓰고 있는 이메일입니다.')
    return email


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': '아이디 또는 비밀번호가 맞지 않습니다.',
        'inactive': '사용이 중지된 계정입니다. 관리자에게 문의해 주세요.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '아이디'
        self.fields['password'].label = '비밀번호'


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email', 'real_name', 'training_hospital')
        labels = {'username': '아이디', 'email': '이메일', 'real_name': '실명', 'training_hospital': '수련병원'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.fields['email'].error_messages['required'] = EMAIL_REQUIRED
        self.fields['real_name'].required = True
        self.fields['real_name'].error_messages['required'] = '실명을 입력해 주세요.'
        self.fields['username'].help_text = '150자 이하 · 영문, 숫자, @ . + - _ 만'
        self.fields['password1'].label = '비밀번호'
        self.fields['password2'].label = '비밀번호 확인'
        self.fields['password2'].help_text = ''

    def clean_email(self):
        return clean_unique_email(self.cleaned_data.get('email'))

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_approved = False          # 관리자가 승인해야 이용 가능
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """마이페이지 정보 수정: 실명·이메일·수련병원만, 모두 검증."""

    class Meta:
        model = CustomUser
        fields = ('real_name', 'email', 'training_hospital')
        labels = {'real_name': '실명', 'email': '이메일', 'training_hospital': '수련병원'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['real_name'].required = True
        self.fields['real_name'].error_messages['required'] = '실명을 입력해 주세요.'
        self.fields['email'].required = True
        self.fields['email'].error_messages['required'] = EMAIL_REQUIRED
        # 예전 임시 주소는 입력칸을 비워서 보여준다
        if self.instance and not has_real_email(self.instance) and not self.is_bound:
            self.initial['email'] = ''

    def clean_real_name(self):
        name = (self.cleaned_data.get('real_name') or '').strip()
        if not name:
            raise forms.ValidationError('실명을 입력해 주세요.')
        return name

    def clean_email(self):
        return clean_unique_email(self.cleaned_data.get('email'), exclude_user=self.instance)


class SafePasswordResetForm(PasswordResetForm):
    """임시 주소(default@default.com 등)를 가진 계정에는 재설정 메일을 보내지 않는다.
    (여러 계정이 같은 임시 주소를 써서, 그 주소를 가진 누군가가 남의 계정을 재설정할 수 있었다)"""

    def get_users(self, email):
        if (email or '').strip().lower() in PLACEHOLDER_EMAILS:
            return iter(())
        return super().get_users(email)
