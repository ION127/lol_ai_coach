"""
Celery 애플리케이션 인스턴스 + Beat 스케줄.

워커 실행:
    celery -A app.workers.celery_app worker --loglevel=info -c 2

Beat 실행 (스케줄러):
    celery -A app.workers.celery_app beat --loglevel=info
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("lol_coach")
celery_app.config_from_object("app.core.celery_config")

# ── Celery Beat 스케줄 (정기 작업) ───────────────────────────────
celery_app.conf.beat_schedule = {
    "collect-challenger-kr": {
        "task": "app.workers.analysis_worker.collect_benchmark",
        "schedule": crontab(hour=4, minute=0),   # 매일 04:00 UTC
        "args": ["KR"],
    },
    "collect-challenger-euw": {
        "task": "app.workers.analysis_worker.collect_benchmark",
        "schedule": crontab(hour=4, minute=30),  # 매일 04:30 UTC
        "args": ["EUW1"],
    },
    "collect-challenger-na": {
        "task": "app.workers.analysis_worker.collect_benchmark",
        "schedule": crontab(hour=5, minute=0),   # 매일 05:00 UTC
        "args": ["NA1"],
    },
}

# ── 태스크 자동 발견 ──────────────────────────────────────────────
celery_app.autodiscover_tasks(["app.workers"])
