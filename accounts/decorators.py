from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def is_member(user):
    """승인된 회원(일반 승인 또는 특별 승인)."""
    return user.is_authenticated and (user.is_approved or user.is_specially_approved)


def user_is_approved(function=None):
    """승인된 회원만 들어올 수 있는 화면.
    - 로그인 전: 로그인 화면으로 (로그인하면 원래 화면으로 돌아온다)
    - 로그인했지만 승인 전: 승인 대기 안내 화면으로"""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not is_member(request.user):
                return redirect('approval_pending')
            return view_func(request, *args, **kwargs)
        return _wrapped_view

    if function:
        return decorator(function)
    return decorator


def user_is_specially_approved(function=None):
    """특별 승인 회원만 들어올 수 있는 화면."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated and request.user.is_specially_approved:
                return view_func(request, *args, **kwargs)
            return redirect('home')
        return _wrapped_view

    if function:
        return decorator(function)
    return decorator
