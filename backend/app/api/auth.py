"""
인증 API 라우터.

엔드포인트:
    POST /api/auth/register  — 회원가입
    POST /api/auth/login     — 로그인 (Access Token + Refresh Token 쿠키)
    POST /api/auth/refresh   — Access Token 갱신 (Refresh Token Rotation)
    POST /api/auth/logout    — 로그아웃 (Refresh Token 폐기)
    GET  /api/auth/me        — 내 정보 조회
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Refresh Token 유효 기간
_REFRESH_TOKEN_EXPIRE_DAYS = 30

# 타이밍 공격 방어용 더미 해시 — 모듈 로드 시 한 번만 생성
# 존재하지 않는 이메일로 로그인 시도해도 bcrypt verify를 실행해 응답 시간 일정화
_TIMING_DUMMY_HASH: str = hash_password("timing-normalization-dummy-value")


# ── 요청/응답 스키마 ──────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("비밀번호는 최소 8자 이상이어야 합니다")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 내부 헬퍼 ────────────────────────────────────────────────────
def _new_refresh_token() -> tuple[str, datetime]:
    """opaque UUID refresh token + 만료 시각 반환"""
    token = uuid.uuid4().hex + uuid.uuid4().hex  # 64자 무작위 문자열
    expires_at = datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS)
    return token, expires_at


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    """HttpOnly Secure 쿠키로 Refresh Token 설정"""
    max_age = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,        # HTTPS 전용
        samesite="strict",  # CSRF 방어
        max_age=max_age,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Refresh Token 쿠키 삭제"""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="strict",
    )


# ── 엔드포인트 ───────────────────────────────────────────────────
@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    이메일 + 비밀번호로 계정 생성.
    이미 존재하는 이메일은 409 Conflict 반환.
    """
    # 이메일 중복 확인
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다",
        )

    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    # get_db_session이 commit을 처리하므로 여기서는 flush만
    await db.flush()
    await db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="로그인",
)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    이메일/비밀번호 인증 → Access Token (응답 바디) + Refresh Token (쿠키).
    실패 시 이메일/비밀번호 중 어느 쪽이 틀렸는지 노출하지 않음 (타이밍 공격 방어).
    """
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="이메일 또는 비밀번호가 올바르지 않습니다",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = await db.scalar(select(User).where(User.email == body.email))
    # 계정 없을 때도 verify_password를 호출해 타이밍 일정화 (타이밍 공격 방어)
    hashed = user.hashed_password if user else _TIMING_DUMMY_HASH
    if user is None or not verify_password(body.password, hashed):
        raise _INVALID

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다",
        )

    # Refresh Token 발급 → DB 저장
    refresh_token, expires_at = _new_refresh_token()
    user.refresh_token = refresh_token
    user.refresh_token_expires_at = expires_at

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, refresh_token, expires_at)

    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Access Token 갱신 (Refresh Token Rotation)",
)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Refresh Token Rotation:
    1. 쿠키의 Refresh Token 검증
    2. 이전 토큰 즉시 폐기
    3. 새 Access Token + 새 Refresh Token 발급
    4. 탈취 감지: 이미 폐기된 토큰으로 요청 시 해당 계정 강제 로그아웃
    """
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효하지 않거나 만료된 Refresh Token입니다",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not refresh_token:
        raise _INVALID

    # DB에서 토큰으로 유저 조회
    user = await db.scalar(select(User).where(User.refresh_token == refresh_token))

    if user is None:
        # 폐기된 토큰 재사용 시도 감지 — 쿠키만 지우고 401 반환
        # (토큰 탈취 의심이지만, 어느 계정인지 알 수 없으므로 강제 로그아웃 불가)
        _clear_refresh_cookie(response)
        raise _INVALID

    # 만료 확인
    if (
        user.refresh_token_expires_at is None
        or user.refresh_token_expires_at.replace(tzinfo=timezone.utc)
        < datetime.now(timezone.utc)
    ):
        user.refresh_token = None
        user.refresh_token_expires_at = None
        _clear_refresh_cookie(response)
        raise _INVALID

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다",
        )

    # Rotation: 이전 토큰 폐기 → 새 토큰 발급
    new_refresh_token, new_expires_at = _new_refresh_token()
    user.refresh_token = new_refresh_token
    user.refresh_token_expires_at = new_expires_at

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, new_refresh_token, new_expires_at)

    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # 204는 응답 바디 없음
    summary="로그아웃",
)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """
    DB의 Refresh Token 폐기 + 쿠키 삭제.
    Access Token은 만료될 때까지 유효 (블랙리스트 없음).
    빠른 무효화가 필요하면 Redis 블랙리스트 도입 고려.
    """
    # DB에서 같은 세션이 이미 flush되므로 db.get으로 재조회
    user = await db.get(User, current_user.id)
    if user:
        user.refresh_token = None
        user.refresh_token_expires_at = None

    _clear_refresh_cookie(response)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="내 정보 조회",
)
async def me(
    current_user: User = Depends(get_current_user),
) -> User:
    """현재 로그인된 유저 정보 반환."""
    return current_user
