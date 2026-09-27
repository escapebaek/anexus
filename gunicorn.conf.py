"""gunicorn 설정 (gunicorn 이 프로젝트 폴더의 이 파일을 자동으로 읽는다).

배포 때 DB 마이그레이션이 빠지는 일을 막는다: Render 대시보드의 Build Command 에 migrate 가
없으면 새 코드가 없는 DB 열을 찾다가 500 오류가 난다 (2026-09 schedule 0012 사례).
서버가 뜰 때(워커를 만들기 전 한 번) migrate 를 실행해 두면 설정과 관계없이 항상 맞춰진다.
"""
import logging


def on_starting(server):
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "anhub.settings")
    django.setup()
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=1)
    except Exception:
        # 마이그레이션이 실패해도 서버는 띄운다 (원인은 로그로 확인)
        logging.getLogger("gunicorn.error").exception("startup migrate failed")
