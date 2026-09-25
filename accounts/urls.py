from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .views import in_korean as ko

urlpatterns = [
    path('login/', ko(views.login_view), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('register/', ko(views.register), name='register'),
    path('pending/', views.approval_pending, name='approval_pending'),
    path('mypage/', ko(views.mypage), name='mypage'),
    path('password_change/', ko(views.SitePasswordChangeView.as_view()), name='password_change'),
    # 비밀번호 찾기
    path('password_reset/', ko(views.SitePasswordResetView.as_view()), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', ko(auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete')
    )), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html'
    ), name='password_reset_complete'),
]
