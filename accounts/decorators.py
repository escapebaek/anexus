from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

def user_is_approved(function=None):
    """
    Decorator for views that checks that the logged in user is approved.
    """
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and u.is_approved,
        login_url='login',
        redirect_field_name=None
    )
    if function:
        return actual_decorator(function)
    return actual_decorator

def user_is_specially_approved(function=None):
    """
    Decorator for views that checks that the logged-in user is specially approved.
    """
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated and request.user.is_specially_approved:
                return view_func(request, *args, **kwargs)
            return redirect('home')  # Redirect to home page
        return _wrapped_view

    if function:
        return decorator(function)
    return decorator
