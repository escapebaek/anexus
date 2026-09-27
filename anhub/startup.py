"""서버가 뜰 때 DB 마이그레이션을 맞춘다.

Render 대시보드의 Build Command 에 migrate 가 없어 새 코드가 없는 DB 열·테이블을 찾다가
500 오류가 난 적이 있다 (schedule 0012, land 0001). gunicorn 설정 파일(gunicorn.conf.py)로도
해 봤지만 Render 의 시작 방식에서는 읽히지 않았다. 그래서 어떤 방식으로 시작하든 반드시
불리는 wsgi.py 에서 실행한다.

워커가 여러 개면 동시에 불리므로 Postgres advisory lock 으로 한 번에 하나만 돌게 하고,
나머지는 기다렸다가 할 일이 없음을 확인하고 지나간다. 실패해도 서버는 뜬다 (로그로 확인).
"""
import logging

logger = logging.getLogger(__name__)
MIGRATE_LOCK_ID = 842_310_001  # 임의의 고정 번호 (이 앱의 마이그레이션 잠금)


def migrate_on_startup():
    from django.core.management import call_command
    from django.db import connection

    try:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("select pg_advisory_lock(%s)", [MIGRATE_LOCK_ID])
            try:
                call_command("migrate", interactive=False, verbosity=1)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("select pg_advisory_unlock(%s)", [MIGRATE_LOCK_ID])
        else:
            # 개발용 SQLite 등: 같은 컴퓨터의 워커끼리만 겹치지 않게 파일 잠금
            import fcntl
            import tempfile
            from pathlib import Path

            with open(Path(tempfile.gettempdir()) / "anexus-migrate.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    call_command("migrate", interactive=False, verbosity=1)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
    except Exception:
        logger.exception("startup migrate failed")
    finally:
        connection.close()
