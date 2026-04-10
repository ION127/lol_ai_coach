"""
Celery 분석 작업.

핵심 태스크:
    run_analysis(analysis_id, s3_key)  — .rofl 파일 분석 전체 파이프라인
    collect_benchmark(region)          — 챌린저 벤치마크 데이터 수집 (Beat 스케줄)

Celery는 동기 컨텍스트 → asyncpg 대신 psycopg2 (SyncSessionLocal) 사용.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Any

import redis as redis_lib

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.models.analysis import AnalysisRecord
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Redis 클라이언트 (동기) ───────────────────────────────────────
_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)

# ── 진행률 단계 정의 ─────────────────────────────────────────────
PROGRESS_STEPS: dict[str, int] = {
    "download": 10,
    "parse": 25,
    "stage1": 45,   # Wave/Tempo/Macro/Composition/GameState
    "stage2": 60,   # Combat
    "stage3": 70,   # Predictive/Intent
    "layers": 85,
    "script": 95,
    "complete": 100,
}


# ── 내부 헬퍼 ────────────────────────────────────────────────────
def _publish_progress(analysis_id: str, step: str, pct: int) -> None:
    """
    Redis Pub/Sub + Key로 이중 발행.
    - Pub/Sub: WebSocket 핸들러가 실시간 구독
    - Key: 재연결 시 최신 상태 즉시 조회 가능 (1시간 TTL)
    """
    payload = json.dumps({"step": step, "pct": pct, "analysis_id": analysis_id})
    try:
        _redis.publish(f"analysis_progress:{analysis_id}", payload)
        _redis.setex(f"analysis_progress_pct:{analysis_id}", 3600, str(pct))
    except Exception:
        logger.warning("Redis publish 실패 (analysis_id=%s)", analysis_id, exc_info=True)


def _update_status(
    analysis_id: str,
    status: str,
    error_message: str | None = None,
    data_quality: str | None = None,
) -> None:
    """AnalysisRecord 상태 동기 업데이트 (SyncSessionLocal)"""
    with SyncSessionLocal() as db:
        record = db.get(AnalysisRecord, analysis_id)
        if record is None:
            logger.error("AnalysisRecord not found: %s", analysis_id)
            return
        record.status = status
        if error_message is not None:
            record.error_message = error_message
        if data_quality is not None:
            record.data_quality = data_quality
        if status in ("complete", "failed"):
            record.completed_at = datetime.now(timezone.utc)
        db.commit()


def _load_metadata(analysis_id: str) -> dict[str, Any]:
    """AnalysisRecord.metadata_json 조회"""
    with SyncSessionLocal() as db:
        record = db.get(AnalysisRecord, analysis_id)
        if record is None or not record.metadata_json:
            return {}
        return json.loads(record.metadata_json)


def _save_analysis_result(
    analysis_id: str,
    layers: dict[str, Any],
    script: str,
    data_quality: str,
) -> None:
    """분석 결과 DB 저장"""
    with SyncSessionLocal() as db:
        record = db.get(AnalysisRecord, analysis_id)
        if record is None:
            logger.error("AnalysisRecord not found: %s", analysis_id)
            return
        record.status = "complete"
        record.data_quality = data_quality
        record.completed_at = datetime.now(timezone.utc)
        record.layer1_json = json.dumps(layers.get("layer1", {}))
        record.layer2_json = json.dumps(layers.get("layer2", {}))
        record.layer3_json = json.dumps(layers.get("layer3", {}))
        record.layer4_json = json.dumps(layers.get("layer4", {}))
        record.script_json = script
        db.commit()


# ── 메인 분석 태스크 ─────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="app.workers.analysis_worker.run_analysis",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,   # 5분 — SoftTimeLimitExceeded (graceful 종료)
    time_limit=360,        # 6분 — 프로세스 강제 종료
    ignore_result=False,
    acks_late=True,        # 성공 후 ack → 재시작 시 재처리 보장
)
def run_analysis(self, analysis_id: str, s3_key: str) -> dict[str, Any]:
    """
    .rofl 파일 분석 전체 파이프라인.

    1. 중복 제출 방지 (Redis SETNX)
    2. DB 상태 → "processing"
    3. S3 다운로드
    4. .rofl 파싱
    5. 9-엔진 분석 파이프라인
    6. Layer 생성
    7. 코칭 스크립트 생성
    8. 결과 저장
    9. S3 원본 삭제
    10. 완료 알림 (Pub/Sub)
    """
    try:
        from billiard.exceptions import SoftTimeLimitExceeded  # Celery 내부
    except ImportError:
        SoftTimeLimitExceeded = Exception  # fallback

    try:
        # ── 1. 중복 제출 방지 ──────────────────────────────────────
        submitted_key = f"submitted:{analysis_id}"
        if not _redis.set(submitted_key, "1", nx=True, ex=3600):
            logger.info("중복 분석 요청 무시: %s", analysis_id)
            return {"status": "already_submitted"}

        # ── 2. DB 상태 업데이트 ────────────────────────────────────
        _update_status(analysis_id, "processing")
        _publish_progress(analysis_id, "download", 0)

        # ── 3. S3 다운로드 ─────────────────────────────────────────
        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        with tempfile.NamedTemporaryFile(suffix=".rofl", delete=False) as tmp:
            tmp_path = tmp.name

        s3.download_file(settings.AWS_S3_BUCKET, s3_key, tmp_path)
        _publish_progress(analysis_id, "download", PROGRESS_STEPS["download"])

        # ── 4. 파싱 ────────────────────────────────────────────────
        # TODO: parser 모듈 구현 후 활성화
        # from app.parser.resilience import RoflResilienceLayer
        # metadata = _load_metadata(analysis_id)
        # match_id = metadata.get("match_id", "")
        # resilience = RoflResilienceLayer()
        # parse_result = resilience.parse_with_fallback(tmp_path, match_id)
        _publish_progress(analysis_id, "parse", PROGRESS_STEPS["parse"])

        # ── 5-7. 분석 + Layer + 스크립트 ──────────────────────────
        # TODO: analysis, layer, coaching 모듈 구현 후 활성화
        # import asyncio
        # from app.analysis.pipeline import run_analysis_pipeline
        # from app.layer.builder import LayerBuilder
        # from app.coaching.script_generator import CoachingScriptGenerator
        # ctx = asyncio.run(run_analysis_pipeline(...))
        # layers = LayerBuilder().build_all(ctx)
        # script = asyncio.run(CoachingScriptGenerator().generate(...))
        _publish_progress(analysis_id, "stage1", PROGRESS_STEPS["stage1"])
        _publish_progress(analysis_id, "stage2", PROGRESS_STEPS["stage2"])
        _publish_progress(analysis_id, "stage3", PROGRESS_STEPS["stage3"])
        _publish_progress(analysis_id, "layers", PROGRESS_STEPS["layers"])
        _publish_progress(analysis_id, "script", PROGRESS_STEPS["script"])

        # ── 8. 결과 저장 (임시 stub) ───────────────────────────────
        _save_analysis_result(
            analysis_id,
            layers={"layer1": {}, "layer2": {}, "layer3": {}, "layer4": {}},
            script="{}",
            data_quality="STUB",
        )

        # ── 9. S3 원본 삭제 ────────────────────────────────────────
        try:
            s3.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=s3_key)
        except Exception:
            logger.warning("S3 원본 삭제 실패 (key=%s)", s3_key, exc_info=True)

        # ── 10. 완료 알림 ──────────────────────────────────────────
        _publish_progress(analysis_id, "complete", PROGRESS_STEPS["complete"])
        _redis.publish(
            f"analysis_progress:{analysis_id}",
            json.dumps({"step": "complete", "pct": 100, "analysis_id": analysis_id}),
        )

        return {"status": "complete", "analysis_id": analysis_id}

    except SoftTimeLimitExceeded:
        _update_status(analysis_id, "failed", "분석 시간 초과 (5분)")
        raise  # Celery가 재시도 처리

    except Exception as exc:
        logger.exception("분석 실패 (analysis_id=%s)", analysis_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        _update_status(analysis_id, "failed", str(exc))
        return {"status": "failed", "error": str(exc)}


# ── 벤치마크 수집 태스크 (Beat 스케줄) ───────────────────────────
@celery_app.task(
    name="app.workers.analysis_worker.collect_benchmark",
    soft_time_limit=600,
    time_limit=660,
)
def collect_benchmark(region: str) -> dict[str, Any]:
    """
    챌린저 리그 경기 데이터 수집 → BenchmarkStat / MatchupStat 업데이트.
    TODO: benchmark 모듈 구현 후 활성화.
    """
    logger.info("벤치마크 수집 시작: region=%s", region)
    # from app.benchmark.collector import BenchmarkCollector
    # collector = BenchmarkCollector()
    # result = collector.collect(region)
    # return result
    return {"status": "stub", "region": region}
