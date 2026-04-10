"""
pytest 공유 픽스처.

- 인메모리 SQLite (aiosqlite) 로 빠른 DB 테스트
- FastAPI TestClient → httpx.AsyncClient (ASGI transport)
- get_db_session 의존성 오버라이드

주의: SQLite는 postgresql.JSON을 TEXT로 처리하므로
      PostgreSQL 전용 JSON 연산자(->>, @>) 테스트는 별도 PG 환경 필요.
"""
from __future__ import annotations

import os

# ── 앱 모듈 임포트 전에 환경변수 설정 ───────────────────────────
# database.py가 임포트 시점에 엔진을 생성하므로, settings가 로드되기 전에
# SQLite URL을 주입해야 asyncpg 드라이버 의존성을 우회할 수 있음
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

# 앱 모듈 임포트 (환경변수 설정 이후)
import app.main as _main_module  # noqa: E402
from app.core.database import Base, get_db_session  # noqa: E402
from app.main import app as _fastapi_app  # noqa: E402

# ── 인메모리 SQLite 엔진 ──────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
_TestSessionLocal = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    """세션 시작 시 테이블 생성, 종료 시 삭제"""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """
    테스트마다 독립적인 DB 세션.
    테스트 종료 후 ROLLBACK으로 데이터 격리.

    SQLAlchemy 2.x: async_sessionmaker로 생성, rollback으로 격리.
    """
    async with _TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """
    get_db_session 의존성을 테스트 세션으로 교체한 AsyncClient.
    main.py의 engine을 테스트용 SQLite 엔진으로 교체해
    lifespan의 DB 연결 확인도 SQLite로 동작하게 함.
    """
    async def _override_get_db():
        yield db_session

    # engine을 테스트 엔진으로 교체 (lifespan의 SELECT 1도 SQLite로 동작)
    original_engine = _main_module.engine
    _main_module.engine = _test_engine

    _fastapi_app.dependency_overrides[get_db_session] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=_fastapi_app),
        base_url="https://test",  # Secure 쿠키 전송을 위해 https 사용
    ) as ac:
        yield ac

    _main_module.engine = original_engine
    _fastapi_app.dependency_overrides.clear()
