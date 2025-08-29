from django.urls import path
from .views import login_view, register, mypage, update_user_info
from django.contrib.auth.views import LogoutView, PasswordChangeView, PasswordChangeDoneView
from django.urls import reverse_lazy

urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('register/', register, name='register'),
    path('password_change/', PasswordChangeView.as_view(
        template_name='accounts/password_change.html',
        success_url=reverse_lazy('mypage')  # MyPage로 리디렉션
    ), name='password_change'),
    path('password-change-done/', PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html'
    ), name='password_change_done'),
    path('mypage/', mypage, name='mypage'),
    path('mypage/update/', update_user_info, name='update_user_info'),
]
