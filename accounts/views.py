from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView, PasswordResetView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme

from . import ratelimit
from .decorators import is_member
from .forms import CustomUserCreationForm, LoginForm, ProfileForm, SafePasswordResetForm, has_real_email
from .notifications import notify_admins_of_signup

LOGIN_FAILURES_PER_ACCOUNT = 5      # 같은 IP·같은 아이디로 10분에 5번 틀리면 잠시 막는다
LOGIN_FAILURES_PER_IP = 20          # 같은 IP 에서 10분에 20번 (여러 아이디 대입 방지)
LOGIN_WINDOW = 10 * 60
RESET_REQUESTS_PER_IP = 5           # 비밀번호 찾기 메일: 1시간에 5번
RESET_WINDOW = 60 * 60
SIGNUPS_PER_IP = 10                 # 가입: 1시간에 10번
SIGNUP_WINDOW = 60 * 60


def in_korean(view):
    """계정 화면에서만 Django 기본 문구(비밀번호 규칙·오류 메시지)를 한국어로."""
    def wrapped(request, *args, **kwargs):
        with translation.override('ko'):
            response = view(request, *args, **kwargs)
            if hasattr(response, 'render') and not getattr(response, 'is_rendered', True):
                response.render()
            return response
    wrapped.__name__ = getattr(view, '__name__', 'view')
    return wrapped


def _safe_next(request):
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return ''


def login_view(request):
    next_url = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(next_url or 'home')

    form = LoginForm(request, data=request.POST or None)
    ip = ratelimit.client_ip(request)
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip().lower()
        account_key = f'login:{ip}:{username}'
        ip_key = f'login:{ip}'
        if ratelimit.is_limited(account_key, LOGIN_FAILURES_PER_ACCOUNT) or ratelimit.is_limited(ip_key, LOGIN_FAILURES_PER_IP):
            form = LoginForm(request)
            form.initial['username'] = request.POST.get('username', '')
            messages.error(request, '로그인 시도가 너무 많습니다. 10분 뒤에 다시 시도해 주세요.')
        elif form.is_valid():
            ratelimit.reset(account_key)
            login(request, form.get_user())
            return redirect(next_url or 'home')
        else:
            ratelimit.record(account_key, LOGIN_WINDOW)
            ratelimit.record(ip_key, LOGIN_WINDOW)
    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})


def register(request):
    if request.user.is_authenticated:
        return redirect('home')
    ip_key = f'signup:{ratelimit.client_ip(request)}'
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if ratelimit.is_limited(ip_key, SIGNUPS_PER_IP):
            messages.error(request, '가입 요청이 너무 많습니다. 잠시 뒤에 다시 시도해 주세요.')
        elif form.is_valid():
            ratelimit.record(ip_key, SIGNUP_WINDOW)
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            notify_admins_of_signup(request, user)
            return redirect('approval_pending')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def approval_pending(request):
    if is_member(request.user):
        return redirect('home')
    return render(request, 'accounts/approval_pending.html')


@login_required
def mypage(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, '회원 정보를 저장했습니다.')
            return redirect('mypage')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'accounts/mypage.html', {
        'form': form,
        'needs_email': not has_real_email(request.user),
        'is_member': is_member(request.user),
    })


class SitePasswordChangeView(PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('mypage')

    def form_valid(self, form):
        messages.success(self.request, '비밀번호를 바꿨습니다.')
        return super().form_valid(form)


class SitePasswordResetView(PasswordResetView):
    """비밀번호 찾기: 메일 설정 전에는 안내만 하고, IP 당 요청 횟수를 제한한다."""
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.html'
    subject_template_name = 'accounts/password_reset_subject.txt'
    form_class = SafePasswordResetForm
    success_url = reverse_lazy('password_reset_done')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['email_ready'] = settings.EMAIL_CONFIGURED or settings.DEBUG
        return context

    def post(self, request, *args, **kwargs):
        if not (settings.EMAIL_CONFIGURED or settings.DEBUG):
            return self.get(request, *args, **kwargs)
        key = f'reset:{ratelimit.client_ip(request)}'
        if ratelimit.is_limited(key, RESET_REQUESTS_PER_IP):
            messages.error(request, '요청이 너무 많습니다. 1시간 뒤에 다시 시도해 주세요.')
            return self.get(request, *args, **kwargs)
        ratelimit.record(key, RESET_WINDOW)
        return super().post(request, *args, **kwargs)
