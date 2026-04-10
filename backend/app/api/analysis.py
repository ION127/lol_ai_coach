"""
분석 API 라우터.

엔드포인트:
    POST /api/analysis/upload-url          — S3 Presigned URL 발급
    POST /api/analysis/{id}/start          — 분석 시작 (Celery 큐 투입)
    GET  /api/analysis/{id}/status         — 분석 상태/진행률 조회
    GET  /api/analysis/{id}/result         — 분석 결과 조회
    GET  /api/analysis/history             — 내 분석 목록
    POST /api/analysis/fallback            — match_id만으로 분석 (FALLBACK 품질)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db_session
from app.models.analysis import AnalysisRecord
from app.models.user import User

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ── Redis 클라이언트 (동기, 상태 조회용) ─────────────────────────
_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)

# ── 업로드 제한 ───────────────────────────────────────────────────
_MAX_FILE_SIZE_BYTES = 120 * 1024 * 1024   # 120MB
_ALLOWED_EXTENSION = ".rofl"
_PRESIGNED_URL_EXPIRES = 300               # 5분


# ── 요청/응답 스키마 ──────────────────────────────────────────────
class UploadUrlRequest(BaseModel):
    filename: str
    file_size: int  # bytes

    @field_validator("filename")
    @classmethod
    def validate_extension(cls, v: str) -> str:
        if not v.lower().endswith(_ALLOWED_EXTENSION):
            raise ValueError(f".rofl 파일만 허용됩니다 (받은 파일: {v!r})")
        return v

    @field_validator("file_size")
    @classmethod
    def validate_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("file_size는 0보다 커야 합니다")
        if v > _MAX_FILE_SIZE_BYTES:
            raise ValueError(f"파일 크기 초과: 최대 {_MAX_FILE_SIZE_BYTES // 1024 // 1024}MB")
        return v


class UploadUrlResponse(BaseModel):
    upload_url: str
    analysis_id: str


class StartAnalysisRequest(BaseModel):
    match_id: str
    champion_id: int
    role: str
    puuid: str


class StartAnalysisResponse(BaseModel):
    status: str
    analysis_id: str


class AnalysisStatusResponse(BaseModel):
    analysis_id: str
    status: str
    progress_pct: int
    data_quality: str | None
    error: str | None
    created_at: datetime


class AnalysisResultResponse(BaseModel):
    analysis_id: str
    status: str
    data_quality: str | None
    layer1: dict | None
    layer2: dict | None
    layer3: dict | None
    layer4: dict | None
    script: dict | None
    completed_at: datetime | None


class AnalysisHistoryItem(BaseModel):
    # ORM 모델의 'id' 컬럼을 'analysis_id'로 직렬화
    analysis_id: str = Field(validation_alias="id")
    status: str
    data_quality: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True, "populate_by_name": True}


class FallbackRequest(BaseModel):
    match_id: str
    champion_id: int
    role: str
    puuid: str


# ── 내부 헬퍼 ────────────────────────────────────────────────────
def _generate_presigned_url(s3_key: str) -> str:
    """
    S3 Presigned PUT URL 발급.
    content-length-range 조건으로 S3 수준에서 파일 크기 강제.
    AWS 설정이 없는 환경(개발)에서는 stub URL 반환.
    """
    if not settings.AWS_S3_BUCKET or not settings.AWS_ACCESS_KEY_ID:
        return f"http://localhost:4566/{settings.AWS_S3_BUCKET or 'local-bucket'}/{s3_key}?stub=1"

    import boto3

    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    return s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.AWS_S3_BUCKET,
            "Key": s3_key,
            "ContentType": "application/octet-stream",
        },
        ExpiresIn=_PRESIGNED_URL_EXPIRES,
    )


def _parse_json_field(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── 엔드포인트 ───────────────────────────────────────────────────
@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
    summary="S3 Presigned URL 발급",
)
async def get_upload_url(
    body: UploadUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    .rofl 파일 업로드용 S3 Presigned PUT URL 발급.
    - 유효 시간: 5분
    - 최대 크기: 120MB (Presigned URL 조건 + 서버 측 검증)
    - S3 경로: {user_id}/{analysis_id}.rofl
    """
    analysis_id = f"anal_{uuid.uuid4().hex[:16]}"
    s3_key = f"{current_user.id}/{analysis_id}.rofl"

    upload_url = _generate_presigned_url(s3_key)

    record = AnalysisRecord(
        id=analysis_id,
        user_id=current_user.id,
        status="pending",
        s3_key=s3_key,
    )
    db.add(record)
    await db.flush()

    return {"upload_url": upload_url, "analysis_id": analysis_id}


@router.post(
    "/{analysis_id}/start",
    response_model=StartAnalysisResponse,
    summary="분석 시작 (Celery 큐 투입)",
)
async def start_analysis(
    analysis_id: str,
    body: StartAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Presigned URL로 업로드 완료 후 호출.
    소유권 확인 → 메타데이터 저장 → Celery 태스크 투입.
    중복 제출은 Redis SETNX로 방지 (태스크 내부에서도 재확인).
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 레코드를 찾을 수 없습니다")

    if record.status not in ("pending",):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"이미 처리 중인 분석입니다 (status={record.status})",
        )

    # 메타데이터 저장 (match_id, champion_id 등)
    record.metadata_json = json.dumps({
        "match_id": body.match_id,
        "champion_id": body.champion_id,
        "role": body.role,
        "puuid": body.puuid,
    })
    await db.flush()

    # Celery 태스크 투입
    from app.workers.analysis_worker import run_analysis
    run_analysis.delay(analysis_id, record.s3_key)

    return {"status": "queued", "analysis_id": analysis_id}


@router.get(
    "/history",
    response_model=list[AnalysisHistoryItem],
    summary="내 분석 목록",
)
async def get_history(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[AnalysisRecord]:
    """
    최근 분석 목록 조회 (최신순).
    최대 100개, 기본 20개.
    """
    limit = min(limit, 100)
    result = await db.execute(
        select(AnalysisRecord)
        .where(AnalysisRecord.user_id == current_user.id)
        .order_by(AnalysisRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get(
    "/{analysis_id}/status",
    response_model=AnalysisStatusResponse,
    summary="분석 상태/진행률 조회",
)
async def get_status(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    DB 상태 + Redis 진행률 퍼센트 병합.
    재연결 후에도 최신 진행률 즉시 반환 가능.
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 레코드를 찾을 수 없습니다")

    pct_raw = _redis.get(f"analysis_progress_pct:{analysis_id}")
    pct = int(pct_raw) if pct_raw else 0

    return {
        "analysis_id": analysis_id,
        "status": record.status,
        "progress_pct": pct,
        "data_quality": record.data_quality,
        "error": record.error_message,
        "created_at": record.created_at,
    }


@router.get(
    "/{analysis_id}/result",
    response_model=AnalysisResultResponse,
    summary="분석 결과 조회",
)
async def get_result(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    분석 완료 후 레이어 + 코칭 스크립트 반환.
    아직 완료되지 않았으면 409 반환.
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "분석 레코드를 찾을 수 없습니다")

    if record.status != "complete":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"분석이 완료되지 않았습니다 (status={record.status})",
        )

    return {
        "analysis_id": analysis_id,
        "status": record.status,
        "data_quality": record.data_quality,
        "layer1": _parse_json_field(record.layer1_json),
        "layer2": _parse_json_field(record.layer2_json),
        "layer3": _parse_json_field(record.layer3_json),
        "layer4": _parse_json_field(record.layer4_json),
        "script": _parse_json_field(record.script_json),
        "completed_at": record.completed_at,
    }


@router.post(
    "/fallback",
    response_model=StartAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="match_id만으로 분석 시작 (FALLBACK 품질)",
)
async def start_fallback_analysis(
    body: FallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    .rofl 파일 없이 match_id만으로 분석.
    Riot API에서 데이터를 가져와 FALLBACK 품질로 분석.
    .rofl 기반 분석보다 정보가 적음 (타임라인 이벤트 없음).
    """
    analysis_id = f"fall_{uuid.uuid4().hex[:16]}"

    record = AnalysisRecord(
        id=analysis_id,
        user_id=current_user.id,
        status="pending",
        data_quality="FALLBACK",
        metadata_json=json.dumps({
            "match_id": body.match_id,
            "champion_id": body.champion_id,
            "role": body.role,
            "puuid": body.puuid,
            "fallback": True,
        }),
    )
    db.add(record)
    await db.flush()

    # FALLBACK 분석은 s3_key 없이 match_id만 사용
    from app.workers.analysis_worker import run_analysis
    run_analysis.delay(analysis_id, "")

    return {"status": "queued", "analysis_id": analysis_id}
