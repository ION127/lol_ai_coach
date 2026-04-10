"""
Celery 설정 모듈.
celery_app.config_from_object("app.core.celery_config") 으로 로드됨.
"""
from app.core.config import settings

# ── 브로커 / 결과 백엔드 ──────────────────────────────────────────
broker_url = settings.CELERY_BROKER_URL
result_backend = settings.CELERY_RESULT_BACKEND

# ── 직렬화 ────────────────────────────────────────────────────────
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]

# ── 시간대 ────────────────────────────────────────────────────────
timezone = "Asia/Seoul"
enable_utc = True

# ── 작업 타임아웃 ─────────────────────────────────────────────────
# .rofl 분석은 최대 5분 (SoftTimeLimitExceeded → graceful 종료)
# Hard limit 6분 (SIGKILL)
task_soft_time_limit = 300
task_time_limit = 360

# ── 워커 동시성 ───────────────────────────────────────────────────
# 분석 작업은 CPU 집약적 — 한 번에 1개씩 처리
worker_prefetch_multiplier = 1

# ── 재처리 보장 ───────────────────────────────────────────────────
# 작업 성공 후 ack → 워커 재시작 시 재처리 보장
task_acks_late = True

# ── 재시도 설정 ───────────────────────────────────────────────────
task_max_retries = 2
task_default_retry_delay = 30  # 30초 후 재시도

# ── 결과 만료 ─────────────────────────────────────────────────────
result_expires = 3600 * 24  # 24시간 후 결과 삭제

# ── Beat 스케줄 (benchmark 수집) ──────────────────────────────────
# 실제 스케줄은 workers/celery_app.py 에서 celery_app.conf.beat_schedule 로 설정
