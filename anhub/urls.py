"""
URL configuration for anhub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django_ckeditor_5.views import upload_file as ckeditor_upload_file

from accounts.decorators import user_is_approved
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import urlencode


def health(request):
    return HttpResponse('ok')


def admin_login(request):
    """관리자 화면 로그인도 사이트 로그인으로 보낸다 — 거기에만 시도 횟수 제한이 있다
    (기본 /admin/login/ 은 제한 없이 비밀번호를 계속 넣어 볼 수 있었다)."""
    next_url = request.GET.get('next') or ''
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = '/admin/'
    if request.user.is_authenticated:
        # 로그인했지만 관리자가 아니면 여기로 온다 — 다시 로그인으로 보내면 무한 반복
        return redirect(next_url if request.user.is_staff else 'home')
    return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")


urlpatterns = [
    path('health/', health),
    path('admin/login/', admin_login),
    path('admin/', admin.site.urls),
    path('', include('land.urls')),
    path('coag/', include('coag.urls')),
    path('board/', include('board.urls')),
    path('accounts/', include('accounts.urls')),
    path('exam/', include('exam.urls')),
    path('drugdictionary/', include('drugdictionary.urls')),
    path('schedule/', include('schedule.urls')),
    path('record/', include('record.urls')),
    path('journal/', include('journal.urls')),
    path('calculator/', include('calculator.urls')),
    # 게시판 사진 업로드는 승인 회원만 (기본 설정은 로그인만 확인한다)
    path('ckeditor5/image_upload/', user_is_approved(ckeditor_upload_file), name='ck_editor_5_upload_file'),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
    path('api/', include('schedule.urls')),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
