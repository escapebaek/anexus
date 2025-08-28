import os
import django
from django.core.asgi import get_asgi_application

# Django 설정 먼저 로드
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'anhub.settings')
django.setup()

# Django ASGI 앱 초기화
django_asgi_app = get_asgi_application()

# 이후 channels 관련 import
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from chat.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})