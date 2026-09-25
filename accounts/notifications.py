import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


def notify_admins_of_signup(request, user):
    """새 가입 → 관리자(스태프)에게 승인 요청 메일. 메일 설정 전이거나 실패해도 가입은 그대로 진행."""
    from .context_processors import clear_pending_count
    from .models import CustomUser

    clear_pending_count()
    if not settings.EMAIL_CONFIGURED:
        return
    recipients = [e for e in CustomUser.objects.filter(is_staff=True, is_active=True)
                  .exclude(email='').values_list('email', flat=True)]
    if not recipients:
        return
    admin_url = request.build_absolute_uri(reverse('admin:accounts_customuser_changelist') + '?is_approved__exact=0')
    body = (f"새 회원이 가입해 승인을 기다리고 있습니다.\n\n"
            f"아이디: {user.username}\n이름: {user.real_name}\n수련병원: {user.training_hospital}\n이메일: {user.email}\n\n"
            f"승인하기: {admin_url}\n")
    try:
        send_mail('[ANExuS] 가입 승인 요청: ' + user.username, body, None, recipients)
    except Exception:  # 메일 서버 문제로 가입이 막히면 안 된다
        logger.exception('signup notification failed')
