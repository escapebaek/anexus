# anhub/urls.py
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('land.urls')),
    path('coag/', include('coag.urls')),
    path('board/', include('board.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('exam/', include('exam.urls')),
    path('drugdictionary/', include('drugdictionary.urls')),
    path('schedule/', include('schedule.urls')),
    path('record/', include('record.urls')),
    # MDEditor (CKEditor 제거)
    path('mdeditor/', include('mdeditor.urls')),
    # Chat
    path('chat/', include('chat.urls')), 
    path('api/', include('schedule.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)