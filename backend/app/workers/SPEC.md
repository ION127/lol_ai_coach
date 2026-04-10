# Workers Module — SPEC

> `backend/app/workers/`  
> Celery 비동기 작업. 분석 파이프라인 실행 + 벤치마크 수집 + 진행률 발행.

## 구현 진행 상황

| 파일 | 상태 | 비고 |
|------|------|------|
| `celery_app.py` | ✅ 완료 | Celery 인스턴스 + Beat 스케줄 |
| `analysis_worker.py` | ✅ 완료 (stub) | 파이프라인 TODO 포함, parser/analysis/layer/coaching 구현 후 활성화 |

> 마지막 업데이트: 2026-04-10

---

## 파일 목록

```
workers/
├── analysis_worker.py   # 핵심 분석 작업 (run_analysis)
└── celery_app.py        # Celery 앱 인스턴스 + Beat 스케줄
```

---

## celery_app.py

```python
from celery import Celery
from app.core.config import settings

celery_app = Celery("lol_coach")
celery_app.config_from_object("app.core.celery_config")

# Beat 스케줄 (정기 작업)
from celery.schedules import crontab  # 명시적 임포트 필요

celery_app.conf.beat_schedule = {
    "collect-challenger-kr": {
        "task": "benchmark.collect_challenger",
        "schedule": crontab(hour=4, minute=0),   # 매일 04:00 KST
        "args": ["KR"],
    },
    "collect-challenger-euw": {
        "task": "benchmark.collect_challenger",
        "schedule": crontab(hour=4, minute=30),
        "args": ["EUW1"],
    },
}
```

---

## analysis_worker.py

### 작업 설정

```python
@celery_app.task(
    bind=True,
    name="workers.run_analysis",
    max_retries=2,
    default_retry_delay=30,       # 재시도 간격 30초
    soft_time_limit=300,          # 5분 — SoftTimeLimitExceeded (graceful 종료)
    time_limit=360,               # 6분 — 프로세스 강제 종료
    ignore_result=False,
    acks_late=True,               # 성공 후 ack → 재시작 시 재처리 보장
)
def run_analysis(self, analysis_id: str, s3_key: str):
```

### 실행 흐름

```
1. 중복 제출 방지
   Redis SET NX "submitted:{analysis_id}" → 이미 있으면 즉시 반환

2. DB 상태 → "processing"
   AnalysisRecord.status = "processing"

3. S3에서 .rofl 다운로드
   s3_client.download_file(s3_key, tmp_path)

4. 파싱 (RoflResilienceLayer)
   parse_result = resilience.parse_with_fallback(tmp_path, match_id)

5. GameContext 생성 + 분석 파이프라인
   ctx = GameContext(snapshots=..., events=..., metadata=..., data_quality=...)
   ctx = asyncio.run(run_analysis_pipeline(ctx))

6. Layer 생성
   layers = LayerBuilder().build_all(ctx)

7. 코칭 스크립트 생성
   script = asyncio.run(CoachingScriptGenerator().generate(ctx, layers, player_model))

8. PlayerModel 업데이트 (DB)
   player_model_engine.update_model_sync(db, puuid, ctx.player_model["pending_update"])

9. 결과 저장 (_save_analysis_result)
   AnalysisRecord.status = "complete"
   AnalysisRecord.layer1_json = json.dumps(layers["layer1"])
   ...

10. S3 원본 삭제
    s3_client.delete_object(s3_key)

11. 완료 알림 (Redis Pub/Sub)
    redis_client.publish(f"analysis_progress:{analysis_id}", json.dumps({...}))
```

### 진행률 발행

```python
def _publish_progress(analysis_id: str, step: str, pct: int):
    """
    Redis Pub/Sub + Key로 이중 발행.
    - Pub/Sub: WebSocket 핸들러가 실시간 구독
    - Key: 재연결 시 최신 상태 즉시 조회 가능
    """
    payload = json.dumps({"step": step, "pct": pct, "analysis_id": analysis_id})
    redis_client.publish(f"analysis_progress:{analysis_id}", payload)
    redis_client.setex(f"analysis_progress_pct:{analysis_id}", 3600, str(pct))

# 진행률 단계
PROGRESS_STEPS = {
    "download":   10,
    "parse":      25,
    "stage1":     45,   # Wave/Tempo/Macro/Composition/GameState
    "stage2":     60,   # Combat
    "stage3":     70,   # Predictive/Intent
    "layers":     85,
    "script":     95,
    "complete":  100,
}
```

### 에러 핸들링

```python
except SoftTimeLimitExceeded:
    _update_status(analysis_id, "failed", "분석 시간 초과 (5분)")
    raise   # Celery가 재시도 처리

except Exception as exc:
    if self.request.retries < self.max_retries:
        raise self.retry(exc=exc, countdown=30)
    _update_status(analysis_id, "failed", str(exc))
```

### 헬퍼 함수

```python
def _load_metadata(analysis_id: str) -> dict:
    """
    AnalysisRecord.metadata_json 조회.
    Celery는 동기 컨텍스트 → SyncSessionLocal 사용.
    """

def _save_analysis_result(db, analysis_id: str, layers: dict, ctx: GameContext) -> None:
    """
    분석 결과 DB 저장.
    - status = "complete"
    - layer1_json ~ script_json = JSON 직렬화
    - data_quality = ctx.data_quality
    - completed_at = datetime.now(timezone.utc)  # Python 3.12+ deprecated utcnow()
    """
```

---

## 중복 제출 방지 (Redis)

```python
submitted_key = f"submitted:{analysis_id}"
if redis_client.set(submitted_key, "1", nx=True, ex=3600):
    # 처음 제출 → 정상 진행
    pass
else:
    # 중복 요청 → 현재 상태 반환
    return {"status": "already_submitted"}
```

---

## 격리 실행 (보안)

```
분석 워커 컨테이너 네트워크 정책:
- Egress: DB(5432), Redis(6379), S3(443) 만 허용
- 외부 인터넷 차단 → 악성 .rofl 파일이 외부 연결 시도해도 차단
- CPU 제한: 2 vCPU (분석 1개 동시 처리)
- 메모리 제한: 4GB
```
