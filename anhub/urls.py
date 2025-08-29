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
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('land.urls')),
    path('coag/', include('coag.urls')),
    path('calculator/', include('calculator.urls')),
    path('ped/', include('ped.urls')),
    path('board/', include('board.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('exam/', include('exam.urls')),
    path('drugdictionary/', include('drugdictionary.urls')),
    path('schedule/', include('schedule.urls')),
    path('record/', include('record.urls')),
    #CKeditor 추가
    path('ckeditor/', include('ckeditor_uploader.urls')),
    #chat
    path('chat/', include('chat.urls')), 
    # debug
    # path('__debug__/', include('debug_toolbar.urls')),
    path('api/', include('schedule.urls')),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
