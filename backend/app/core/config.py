from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── 데이터베이스 ──────────────────────────────────────────────
    # postgresql+asyncpg://user:pass@host:port/dbname
    DATABASE_URL: str = "postgresql+asyncpg://lol_user:password@localhost:5432/lol_coach"

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── 인증 ─────────────────────────────────────────────────────
    # 최소 32바이트 랜덤 문자열 필수
    # 생성: python -c "import secrets; print(secrets.token_hex(32))"
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production-please"

    # ── AWS ───────────────────────────────────────────────────────
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ── Riot API ──────────────────────────────────────────────────
    RIOT_API_KEY: str = ""

    # ── LLM ───────────────────────────────────────────────────────
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"

    # ── CORS ──────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── 환경 ──────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"  # development | staging | production

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # .env에 알 수 없는 키가 있어도 무시
    )


# 앱 전역 싱글턴 — 모든 모듈에서 이 인스턴스를 임포트해 사용
settings = Settings()
