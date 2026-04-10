from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy import create_engine

from app.core.config import settings


# ── 비동기 엔진 (FastAPI 라우터용) ────────────────────────────────
# SQLite(테스트용)는 풀 설정을 지원하지 않으므로 분기 처리
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    **({} if _is_sqlite else {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,    # RDS idle timeout 방어 (30분)
        "pool_pre_ping": True,   # stale connection 자동 감지
    }),
)

# SQLAlchemy 2.x 권장 팩토리 (async_sessionmaker)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,         # commit 후에도 ORM 객체 접근 가능
)


async def get_db_session():
    """
    FastAPI Depends용 비동기 세션 제너레이터.

    사용법:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── 동기 엔진 (Celery 워커용) ────────────────────────────────────
# Celery는 동기 컨텍스트 → asyncpg 사용 불가 → psycopg2로 자동 변환
_sync_url = (
    settings.DATABASE_URL
    .replace("postgresql+asyncpg", "postgresql+psycopg2")
    .replace("postgresql+aiopg", "postgresql+psycopg2")
)

sync_engine = create_engine(
    _sync_url,
    **({} if _is_sqlite else {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    }),
)

SyncSessionLocal = sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False,
)


# ── ORM Base ──────────────────────────────────────────────────────
# 모든 ORM 모델은 이 Base를 상속해야 Alembic이 스키마를 감지함
class Base(DeclarativeBase):
    pass
