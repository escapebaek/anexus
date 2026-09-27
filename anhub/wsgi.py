"""
WSGI config for anhub project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'anhub.settings')

application = get_wsgi_application()

# 배포 때마다 DB 마이그레이션을 맞춘다 (anhub/startup.py 설명 참고). 끄려면 MIGRATE_ON_STARTUP=0
if os.environ.get('MIGRATE_ON_STARTUP', '1') != '0':
    from anhub.startup import migrate_on_startup

    migrate_on_startup()
