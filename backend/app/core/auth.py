from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session

if TYPE_CHECKING:
    # 순환 임포트 방지: 타입 힌트 전용 (런타임에는 실행 안 됨)
    from app.models.user import User


# ── 상수 ──────────────────────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# auto_error=False → 헤더 없을 때 None 반환 (직접 에러 처리)
bearer_scheme = HTTPBearer(auto_error=False)

# bcrypt 해싱 컨텍스트 (rounds=12 기본값)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 401 예외 객체 (재사용)
_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},  # RFC 6750 §3.1 준수
)


# ── 비밀번호 ──────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    """평문 비밀번호 → bcrypt 해시"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """평문 비밀번호와 bcrypt 해시 비교"""
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────
def create_access_token(user_id: str) -> str:
    """
    user_id를 sub 클레임에 담아 JWT Access Token 발급.
    만료: 1시간 (ACCESS_TOKEN_EXPIRE_MINUTES)
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),  # 발급 시각
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    JWT 디코딩 + 서명/만료 검증.
    실패 시 JWTError 발생 (호출부에서 처리).
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])


# ── FastAPI Dependency ────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> "User":
    """
    Authorization: Bearer <token> 헤더 검증 → User ORM 객체 반환.

    에러 케이스:
    - 헤더 없음          → 401
    - 토큰 만료/위조     → 401
    - DB에 유저 없음     → 401 (탈취된 토큰으로 삭제된 계정 접근 방지)
    - is_active=False    → 403

    사용법:
        @router.get("/me")
        async def me(user: User = Depends(get_current_user)):
            return {"id": user.id, "email": user.email}
    """
    # 런타임 임포트 — 모듈 로드 시 순환 참조 방지
    from app.models.user import User  # noqa: PLC0415

    if credentials is None:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise _CREDENTIALS_EXCEPTION
    except JWTError:
        raise _CREDENTIALS_EXCEPTION

    user = await db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> "User | None":
    """
    인증이 선택적인 엔드포인트용 Dependency.
    토큰 없거나 유효하지 않으면 None 반환 (예외 없음).
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
