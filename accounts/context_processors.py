from django.core.cache import cache


def account_status(request):
    """모든 화면에서 쓰는 계정 상태:
    - 관리자: 가입 승인 대기 인원 (상단 메뉴 알림)
    - 승인 전 회원: 승인 대기 안내"""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    context = {'awaiting_approval': not (user.is_approved or user.is_specially_approved)}
    if user.is_staff:
        count = cache.get('accounts:pending_count')
        if count is None:
            from .models import CustomUser
            count = CustomUser.objects.filter(is_approved=False, is_specially_approved=False, is_active=True).count()
            cache.set('accounts:pending_count', count, 60)
        context['pending_approval_count'] = count
    return context


def clear_pending_count():
    cache.delete('accounts:pending_count')
