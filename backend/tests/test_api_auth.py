"""
api/auth.py 통합 테스트.

실제 HTTP 요청 → FastAPI 앱 → SQLite 인메모리 DB 흐름 검증.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, hash_password
from app.models.user import User


# ── 헬퍼 ────────────────────────────────────────────────────────
async def _create_user(
    db: AsyncSession,
    email: str = "test@example.com",
    password: str = "TestPass1!",
    is_active: bool = True,
) -> User:
    """DB에 테스트 유저 직접 삽입"""
    import uuid

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# ── 회원가입 ─────────────────────────────────────────────────────
class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["is_active"] is True
        assert "id" in data
        assert "hashed_password" not in data  # 비밀번호 노출 금지

    async def test_register_duplicate_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, email="dup@example.com")
        resp = await client.post(
            "/api/auth/register",
            json={"email": "dup@example.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 409

    async def test_register_short_password(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert resp.status_code == 422  # Pydantic validation error

    async def test_register_invalid_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "StrongPass1!"},
        )
        assert resp.status_code == 422


# ── 로그인 ────────────────────────────────────────────────────────
class TestLogin:
    async def test_login_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, email="login@example.com", password="MyPass1!")
        resp = await client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "MyPass1!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # Refresh Token 쿠키 확인
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, email="wrong@example.com", password="correct1!")
        resp = await client.post(
            "/api/auth/login",
            json={"email": "wrong@example.com", "password": "incorrect!"},
        )
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers

    async def test_login_nonexistent_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/login",
            json={"email": "ghost@example.com", "password": "Pass1234!"},
        )
        assert resp.status_code == 401

    async def test_login_inactive_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(
            db_session,
            email="inactive@example.com",
            password="Pass1234!",
            is_active=False,
        )
        resp = await client.post(
            "/api/auth/login",
            json={"email": "inactive@example.com", "password": "Pass1234!"},
        )
        assert resp.status_code == 403


# ── Refresh Token 갱신 ────────────────────────────────────────────
class TestRefresh:
    async def test_refresh_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, email="refresh@example.com", password="Pass1!")

        # 1) 로그인 → Refresh Token 쿠키 획득
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "refresh@example.com", "password": "Pass1!"},
        )
        assert login_resp.status_code == 200

        # 2) Refresh Token으로 새 Access Token 요청
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        # 새 Refresh Token 쿠키 발급 확인 (Rotation)
        assert "refresh_token" in resp.cookies

    async def test_refresh_without_cookie(self, client: AsyncClient):
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401

    async def test_refresh_invalid_token(self, client: AsyncClient):
        client.cookies.set("refresh_token", "invalid-token-value")
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401


# ── 로그아웃 ──────────────────────────────────────────────────────
class TestLogout:
    async def test_logout_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, email="logout@example.com", password="Pass1!")
        await client.post(
            "/api/auth/login",
            json={"email": "logout@example.com", "password": "Pass1!"},
        )

        # Access Token으로 로그아웃
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "logout@example.com", "password": "Pass1!"},
        )
        access_token = login_resp.json()["access_token"]

        resp = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 204

    async def test_logout_without_token(self, client: AsyncClient):
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 401


# ── /me ───────────────────────────────────────────────────────────
class TestMe:
    async def test_me_returns_user_info(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, email="me@example.com", password="Pass1!")
        token = create_access_token(user.id)

        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "me@example.com"
        assert data["id"] == user.id
        assert "hashed_password" not in data

    async def test_me_without_token(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_me_with_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401


# ── Health Check ──────────────────────────────────────────────────
class TestHealthCheck:
    async def test_health_returns_ok(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
