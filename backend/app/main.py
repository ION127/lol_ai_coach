"""
FastAPI 애플리케이션 진입점.

실행:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine


# ── 앱 시작/종료 수명 주기 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 연결 확인, 종료 시 커넥션 풀 정리"""
    # 시작
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    # 종료
    await engine.dispose()


# ── FastAPI 인스턴스 ──────────────────────────────────────────────
app = FastAPI(
    title="LoL AI Coach API",
    version="3.0.0",
    description="League of Legends .rofl Replay Analysis & AI Coaching Service",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────
# "*" 절대 금지 — JWT 쿠키 노출 위험
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,               # Authorization 헤더 + 쿠키 허용
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    max_age=86400,                        # preflight 캐시 24시간
)

# ── 라우터 등록 ──────────────────────────────────────────────────
from app.api import auth  # noqa: E402

app.include_router(auth.router)

from app.api import analysis  # noqa: E402

app.include_router(analysis.router)

# 개발 진행에 따라 주석 해제
# from app.api import chat, benchmark, summoner
# app.include_router(chat.router)
# app.include_router(benchmark.router)
# app.include_router(summoner.router)


# ── Health Check ──────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    """Liveness probe — 프로세스 살아있는지 확인"""
    return {"status": "ok", "version": "3.0.0"}


@app.get("/ready", tags=["health"])
async def ready():
    """
    Readiness probe — 외부 의존성 확인.
    DB + Redis 모두 OK여야 트래픽 수신 가능.
    ECS / K8s readiness probe 용도.
    """
    import json
    from fastapi.responses import JSONResponse

    checks: dict[str, str] = {}

    # DB 확인
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"unreachable: {e}"

    # Redis 확인
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"unreachable: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )
