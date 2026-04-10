import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic Config 객체 ───────────────────────────────────────────
config = context.config

# logging 설정 (alembic.ini 참조)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 모델 메타데이터 로드 ──────────────────────────────────────────
# 모든 모델이 여기서 임포트되어야 Alembic이 스키마 변경을 감지함
from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402, F401  — models/__init__.py 에서 모두 임포트

target_metadata = Base.metadata

# ── DB URL 동적 주입 ──────────────────────────────────────────────
# alembic.ini의 sqlalchemy.url 대신 settings에서 읽어옴
from app.core.config import settings  # noqa: E402

# Alembic은 동기 URL을 원함 — asyncpg → psycopg2 변환
_sync_url = (
    settings.DATABASE_URL
    .replace("postgresql+asyncpg", "postgresql+psycopg2")
    .replace("postgresql+aiopg", "postgresql+psycopg2")
)
config.set_main_option("sqlalchemy.url", _sync_url)


# ── 오프라인 마이그레이션 (SQL 스크립트 생성) ──────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── 온라인 마이그레이션 (비동기 엔진) ────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
