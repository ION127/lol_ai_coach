# Infra — SPEC

> `infra/`  
> 배포 구성, DB 마이그레이션, CI/CD, 모니터링, 보안 정책.

---

## 컴포넌트 구성

| 컴포넌트 | 기술 | 역할 | 배포 |
|---------|------|------|------|
| API Server | FastAPI | 유저 요청, 인증, 결과 제공 | ECS (Fargate) |
| Analysis Worker | Celery | .rofl 파싱, 분석 파이프라인 | ECS (CPU 최적화) |
| Benchmark Worker | Celery Beat | Riot API 챌린저 통계 수집 | ECS (별도 태스크) |
| Database | PostgreSQL 16 | 유저/분석/벤치마크 | RDS (Multi-AZ) |
| Cache/Queue | Redis 7 | Celery 큐, Pub/Sub, 캐시 | ElastiCache |
| File Storage | S3 | .rofl 임시 저장 (파싱 후 즉시 삭제) | S3 |
| Frontend | Next.js | 웹 대시보드 | Vercel |
| Desktop App | Electron | 로컬 파일 탐지/업로드/오버레이 | GitHub Releases |

---

## 단계별 인프라 확장

| 단계 | 일일 유저 | 인프라 | 예상 비용 |
|------|-----------|--------|-----------|
| Phase 1 (MVP) | ~100명 | Oracle Cloud 무료 + Vercel | 월 0원 |
| Phase 2 (성장) | ~1,000명 | AWS ECS + RDS + S3 | 월 10~30만원 |
| Phase 3 (확장) | ~10,000명 | ECS Auto Scaling + RDS Read Replica | 월 50~100만원 |
| Phase 4 (대규모) | ~100,000명 | K8s + CDN + DB 샤딩 | 월 300만원+ |

---

## Docker 구성

### API Server

```dockerfile
# infra/docker/api.Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Analysis Worker (네트워크 격리)

```dockerfile
# infra/docker/worker.Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 분석 워커는 외부 인터넷 접근 차단 (악성 .rofl 방어)
# ECS Task → SecurityGroup Egress: DB(5432), Redis(6379), S3(443) 만 허용
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
```

---

## docker-compose.yml (로컬 개발)

```yaml
version: "3.9"
services:
  api:
    build:
      context: ./backend
      dockerfile: ../infra/docker/api.Dockerfile
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db, redis]

  worker:
    build:
      context: ./backend
      dockerfile: ../infra/docker/worker.Dockerfile
    env_file: .env
    depends_on: [db, redis]

  beat:
    build:
      context: ./backend
      dockerfile: ../infra/docker/worker.Dockerfile
    command: celery -A app.workers.celery_app beat --loglevel=info
    env_file: .env
    depends_on: [redis]

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: lol_coach
      POSTGRES_USER: lol_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

volumes:
  pgdata:
```

---

## Alembic 마이그레이션

```
infra/alembic/
├── env.py
└── versions/
    ├── 0001_initial_schema.py        # users, analysis_records
    ├── 0002_add_benchmark.py         # benchmark_stats, matchup_stats
    ├── 0003_add_player_model.py      # player_models
    └── 0004_add_data_quality_col.py  # analysis_records.data_quality
```

### 무중단 배포 전략
1. nullable 컬럼 추가 (기존 행 영향 없음)
2. 코드 배포 (신규 컬럼 사용 시작)
3. 백그라운드 작업으로 기존 행 백필
4. NOT NULL 제약 추가 (필요 시)

```bash
# CI/CD 파이프라인에서 자동 실행
alembic upgrade head
```

---

## CI/CD (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest --cov=app tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Build & Push Docker images
        run: |
          docker build -f infra/docker/api.Dockerfile -t $ECR_URI/api:$GITHUB_SHA .
          docker push $ECR_URI/api:$GITHUB_SHA

      - name: Run migrations
        run: alembic upgrade head

      - name: Deploy to ECS
        run: aws ecs update-service --service lol-coach-api --force-new-deployment
```

---

## Health Check 엔드포인트

```python
# 반드시 구현 — ECS/K8s liveness/readiness probe

@app.get("/health")
async def health():
    """Liveness probe — 프로세스 살아있는지"""
    return {"status": "ok"}

@app.get("/ready")
async def ready(db=Depends(get_db_session)):
    """
    Readiness probe — 외부 의존성 확인.
    DB + Redis + Celery 모두 OK여야 트래픽 수신.
    """
    checks = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "unreachable"
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unreachable"
    try:
        celery_app.control.inspect(timeout=2).ping()
        checks["celery"] = "ok"
    except Exception:
        checks["celery"] = "unreachable"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ready" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )
```

---

## 보안 정책

### 네트워크
- Analysis Worker: Egress = DB/Redis/S3 만 허용 (외부 인터넷 차단)
- RDS: VPC 내부에서만 접근 (퍼블릭 IP 없음)
- Redis: VPC 내부에서만 접근 + AUTH 패스워드

### S3
```
버킷 정책:
- 퍼블릭 읽기 금지
- Presigned URL로만 접근 (5분 유효)
- 분석 완료 후 즉시 삭제 (Lambda trigger 또는 worker 직접 삭제)
- 유저별 prefix 격리: s3://bucket/{user_id}/*.rofl
```

### API Rate Limiting
```python
# slowapi 사용
RATE_LIMITS = {
    "/api/analysis/upload-url": "20/hour",
    "/api/analysis/{id}/chat":  "60/hour",
    "/api/auth/login":          "10/minute",
    "default":                  "200/minute",
}
```

---

## 모니터링

| 항목 | 도구 |
|------|------|
| 로그 | CloudWatch Logs (ECS) |
| 메트릭 | CloudWatch Metrics + 사용자 정의 지표 |
| 에러 추적 | Sentry |
| APM | (Phase 3~) Datadog 또는 OpenTelemetry |
| 알람 | CloudWatch Alarms → Slack 알림 |

### 핵심 알람 기준
- API P99 응답시간 > 2초
- Celery 큐 대기 > 50개
- Worker 에러율 > 5%
- DB 커넥션 > 80%
