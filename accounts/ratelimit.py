"""간단한 시도 횟수 제한 (로그인·비밀번호 찾기·가입).

Django 캐시(기본: 프로세스 메모리)에 '키 → 시도 횟수'를 창(window) 동안 저장한다.
gunicorn 워커마다 따로 세므로 한도는 대략적이지만, 무차별 대입을 충분히 늦춘다.
"""
from django.core.cache import cache


def client_ip(request):
    """Render 로드밸런서 뒤: X-Forwarded-For 의 첫 주소가 실제 접속 IP."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def is_limited(key, limit):
    return (cache.get(key) or 0) >= limit


def record(key, window):
    """시도 1회 기록. 첫 기록 때 만료 시간(window 초)이 정해진다."""
    if cache.add(key, 1, window):
        return
    try:
        cache.incr(key)
    except ValueError:      # 그 사이 만료됨
        cache.set(key, 1, window)


def reset(key):
    cache.delete(key)
