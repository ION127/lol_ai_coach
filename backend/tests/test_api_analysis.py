"""
api/analysis.py 통합 테스트.

Celery 태스크(`run_analysis.delay`)는 mock으로 우회.
S3 Presigned URL 생성도 mock (AWS 자격증명 불필요).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, hash_password
from app.models.analysis import AnalysisRecord
from app.models.user import User

# patch 대상 모듈을 미리 임포트 (unittest.mock.patch가 모듈을 찾을 수 있도록)
import app.workers.analysis_worker  # noqa: F401


# ── 헬퍼 ────────────────────────────────────────────────────────
async def _create_user(db: AsyncSession, email: str = "analyst@example.com") -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password("Pass1234!"),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _create_record(
    db: AsyncSession,
    user_id: str,
    analysis_id: str | None = None,
    status: str = "pending",
    **kwargs,
) -> AnalysisRecord:
    record = AnalysisRecord(
        id=analysis_id or f"anal_{uuid.uuid4().hex[:16]}",
        user_id=user_id,
        status=status,
        s3_key=f"{user_id}/test.rofl",
        **kwargs,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


def _auth_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ── upload-url ───────────────────────────────────────────────────
class TestUploadUrl:
    @patch("app.api.analysis._generate_presigned_url", return_value="https://s3.stub/key")
    async def test_upload_url_success(self, mock_url, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "upload@example.com")
        resp = await client.post(
            "/api/analysis/upload-url",
            json={"filename": "game.rofl", "file_size": 1024 * 1024},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "upload_url" in data
        assert "analysis_id" in data
        assert data["analysis_id"].startswith("anal_")

    async def test_upload_url_wrong_extension(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "upload2@example.com")
        resp = await client.post(
            "/api/analysis/upload-url",
            json={"filename": "game.mp4", "file_size": 1024},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 422

    async def test_upload_url_too_large(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "upload3@example.com")
        resp = await client.post(
            "/api/analysis/upload-url",
            json={"filename": "game.rofl", "file_size": 200 * 1024 * 1024},  # 200MB
            headers=_auth_headers(user),
        )
        assert resp.status_code == 422

    async def test_upload_url_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/analysis/upload-url",
            json={"filename": "game.rofl", "file_size": 1024},
        )
        assert resp.status_code == 401


# ── start ────────────────────────────────────────────────────────
class TestStartAnalysis:
    @patch("app.workers.analysis_worker.run_analysis")
    async def test_start_success(self, mock_task, client: AsyncClient, db_session: AsyncSession):
        mock_task.delay = MagicMock()
        user = await _create_user(db_session, "start@example.com")
        record = await _create_record(db_session, user.id, status="pending")

        resp = await client.post(
            f"/api/analysis/{record.id}/start",
            json={
                "match_id": "KR_12345",
                "champion_id": 157,
                "role": "MID",
                "puuid": "a" * 78,
            },
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        mock_task.delay.assert_called_once()

    async def test_start_not_found(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "start2@example.com")
        resp = await client.post(
            "/api/analysis/nonexistent/start",
            json={"match_id": "KR_1", "champion_id": 1, "role": "MID", "puuid": "a" * 78},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 404

    async def test_start_other_users_record(self, client: AsyncClient, db_session: AsyncSession):
        owner = await _create_user(db_session, "owner@example.com")
        requester = await _create_user(db_session, "requester@example.com")
        record = await _create_record(db_session, owner.id, status="pending")

        resp = await client.post(
            f"/api/analysis/{record.id}/start",
            json={"match_id": "KR_1", "champion_id": 1, "role": "MID", "puuid": "a" * 78},
            headers=_auth_headers(requester),
        )
        assert resp.status_code == 404

    @patch("app.workers.analysis_worker.run_analysis")
    async def test_start_already_processing(self, mock_task, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "start3@example.com")
        record = await _create_record(db_session, user.id, status="processing")

        resp = await client.post(
            f"/api/analysis/{record.id}/start",
            json={"match_id": "KR_1", "champion_id": 1, "role": "MID", "puuid": "a" * 78},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 409


# ── status ───────────────────────────────────────────────────────
class TestGetStatus:
    @patch("app.api.analysis._redis")
    async def test_status_pending(self, mock_redis, client: AsyncClient, db_session: AsyncSession):
        mock_redis.get.return_value = None
        user = await _create_user(db_session, "status@example.com")
        record = await _create_record(db_session, user.id, status="pending")

        resp = await client.get(
            f"/api/analysis/{record.id}/status",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["progress_pct"] == 0

    @patch("app.api.analysis._redis")
    async def test_status_processing_with_progress(self, mock_redis, client: AsyncClient, db_session: AsyncSession):
        mock_redis.get.return_value = "45"
        user = await _create_user(db_session, "status2@example.com")
        record = await _create_record(db_session, user.id, status="processing")

        resp = await client.get(
            f"/api/analysis/{record.id}/status",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["progress_pct"] == 45

    async def test_status_not_found(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "status3@example.com")
        resp = await client.get(
            "/api/analysis/nonexistent/status",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 404


# ── result ───────────────────────────────────────────────────────
class TestGetResult:
    async def test_result_complete(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "result@example.com")
        record = await _create_record(
            db_session,
            user.id,
            status="complete",
            layer1_json=json.dumps({"cs_per_min": 7.2}),
            script_json=json.dumps({"advice": "CS 올리세요"}),
            data_quality="FULL",
        )

        resp = await client.get(
            f"/api/analysis/{record.id}/result",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert data["layer1"] == {"cs_per_min": 7.2}
        assert data["script"] == {"advice": "CS 올리세요"}

    async def test_result_not_complete(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "result2@example.com")
        record = await _create_record(db_session, user.id, status="processing")

        resp = await client.get(
            f"/api/analysis/{record.id}/result",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 409


# ── history ──────────────────────────────────────────────────────
class TestHistory:
    async def test_history_empty(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "history@example.com")
        resp = await client.get("/api/analysis/history", headers=_auth_headers(user))
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_history_returns_own_records(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "history2@example.com")
        other = await _create_user(db_session, "other@example.com")

        await _create_record(db_session, user.id, status="complete")
        await _create_record(db_session, user.id, status="pending")
        await _create_record(db_session, other.id, status="complete")  # 다른 유저

        resp = await client.get("/api/analysis/history", headers=_auth_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2  # 자신의 것만

    async def test_history_limit(self, client: AsyncClient, db_session: AsyncSession):
        user = await _create_user(db_session, "history3@example.com")
        for _ in range(5):
            await _create_record(db_session, user.id, status="complete")

        resp = await client.get(
            "/api/analysis/history?limit=3",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3


# ── fallback ─────────────────────────────────────────────────────
class TestFallback:
    @patch("app.workers.analysis_worker.run_analysis")
    async def test_fallback_success(self, mock_task, client: AsyncClient, db_session: AsyncSession):
        mock_task.delay = MagicMock()
        user = await _create_user(db_session, "fallback@example.com")

        resp = await client.post(
            "/api/analysis/fallback",
            json={
                "match_id": "KR_99999",
                "champion_id": 238,
                "role": "MID",
                "puuid": "b" * 78,
            },
            headers=_auth_headers(user),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["analysis_id"].startswith("fall_")
        mock_task.delay.assert_called_once()
