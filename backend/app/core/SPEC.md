# Core Module — SPEC

> `backend/app/core/`  
> 앱 전체에서 공유하는 기반 설정: DB 엔진, 인증, 설정값, 공통 예외

---

## 파일 목록

```
core/
├── database.py       # SQLAlchemy 엔진 + 세션 팩토리
├── auth.py           # JWT 발급/검증, get_current_user FastAPI Dependency
├── config.py         # 환경변수 Pydantic Settings
├── exceptions.py     # 공통 HTTPException 래퍼
└── celery_config.py  # Celery 브로커/결과 백엔드 설정
```

---

## database.py

### 역할
- AsyncSession (FastAPI 라우터용) + SyncSession (Celery 워커용) 두 가지 세션 팩토리 제공
- 커넥션 풀 튜닝값 고정

### 핵심 코드

```python
# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy import create_engine
from app.core.config import settings

# ── 비동기 엔진 (FastAPI 라우터용) ────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,          # postgresql+asyncpg://...
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,              # RDS idle timeout 방어
    pool_pre_ping=True,             # stale connection 감지
    echo=settings.ENVIRONMENT == "development",
)

AsyncSessionLocal = async_sessionmaker(   # SQLAlchemy 2.x 권장 팩토리
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db_session():
    """FastAPI Depends용 비동기 세션 제너레이터"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# ── 동기 엔진 (Celery 워커용) ────────────────────────────────────
# asyncpg → psycopg2 자동 변환 (SYNC_DATABASE_URL 별도 설정 불필요)
_sync_url = settings.DATABASE_URL.replace(
    "postgresql+asyncpg", "postgresql+psycopg2"
).replace(
    "postgresql+aiopg", "postgresql+psycopg2"
)
sync_engine = create_engine(
    _sync_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SyncSessionLocal = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)

# ── ORM Base ──────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass
```

---

## auth.py

### 역할
- JWT Access Token 발급/검증
- `get_current_user()` — FastAPI Depends로 모든 인증 필요 라우터에 주입

### 설계 결정
| 항목 | 값 | 이유 |
|------|-----|------|
| Access Token 만료 | 1시간 | 짧게 유지 — 탈취 피해 최소화 |
| Refresh Token 만료 | 30일 | DB 저장 → 탈취 시 즉시 폐기 가능 |
| Refresh Token 전송 | HttpOnly Secure 쿠키 | JS 접근 불가, XSS 방어 |
| 알고리즘 | HS256 | 단일 서버, RS256 불필요 |

### 핵심 코드

```python
# auth.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session

if TYPE_CHECKING:
    from app.models.user import User  # 순환 임포트 방지 (런타임 아님)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

bearer_scheme = HTTPBearer(auto_error=False)  # auto_error=False → 미인증 시 None 반환
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── 비밀번호 ──────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# ── JWT ───────────────────────────────────────────────────────────
def create_access_token(user_id: str) -> str:
    """user_id를 sub 클레임에 담아 JWT 발급 (1시간 유효)"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

# ── FastAPI Dependency ────────────────────────────────────────────
_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},  # RFC 6750 준수
)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> "User":
    """
    Authorization: Bearer <token> 헤더 검증 → User ORM 반환.
    - 토큰 없음 / 만료 / 서명 불일치 → 401
    - 계정 비활성 → 403
    """
    from app.models.user import User  # 런타임 임포트 (순환 방지)

    if credentials is None:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise _CREDENTIALS_EXCEPTION
    except JWTError:
        raise _CREDENTIALS_EXCEPTION

    user = await db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return user
```

---

## config.py

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ── 데이터베이스 ──────────────────────────────────────────────
    DATABASE_URL: str                  # postgresql+asyncpg://user:pass@host/db
    # SYNC_DATABASE_URL 별도 설정 불필요 — database.py에서 asyncpg→psycopg2 자동 변환

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── 인증 ─────────────────────────────────────────────────────
    JWT_SECRET_KEY: str                # 최소 32바이트 랜덤 문자열

    # ── AWS ───────────────────────────────────────────────────────
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ── Riot API ──────────────────────────────────────────────────
    RIOT_API_KEY: str = ""

    # ── LLM ───────────────────────────────────────────────────────
    LLM_API_KEY: str = ""              # Anthropic API Key
    LLM_MODEL: str = "claude-sonnet-4-6"

    # ── CORS ──────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── 환경 ──────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"   # development | staging | production

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,          # 대소문자 구분 없이 환경변수 매핑
    )

settings = Settings()
```

---

## celery_config.py

```python
# celery_config.py
from app.core.config import settings

broker_url          = settings.CELERY_BROKER_URL
result_backend      = settings.CELERY_RESULT_BACKEND
task_serializer     = "json"
result_serializer   = "json"
accept_content      = ["json"]
timezone            = "Asia/Seoul"
enable_utc          = True
task_soft_time_limit = 300   # 5분 graceful
task_time_limit      = 360   # 6분 hard kill
worker_prefetch_multiplier = 1   # 분석 작업은 무거움 — 1개씩 처리
task_acks_late       = True  # 성공 후 ack → 재시작 시 재처리 보장
```

---

## exceptions.py

```python
from fastapi import HTTPException

def not_found(resource: str):
    raise HTTPException(404, f"{resource} not found")

def forbidden(msg: str = "Forbidden"):
    raise HTTPException(403, msg)

def bad_request(msg: str):
    raise HTTPException(400, msg)
```

---

## 의존 관계

```
config.py  ←─────────────── 모든 모듈
database.py ←──────────────  models/, api/, workers/
auth.py     ←──────────────  api/ (모든 인증 필요 라우터)
celery_config.py ←─────────  workers/
```
