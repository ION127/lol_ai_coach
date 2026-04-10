# LoL AI Coach — System Architecture Map

> League of Legends .rofl Replay Analysis & AI Coaching Service  
> Version 3.0 | 2026.04  
> **이 문서는 전체 구조를 보여주는 지도입니다. 각 모듈의 상세 명세는 링크된 SPEC.md를 참조하세요.**

---

## 프로젝트 구조

```
lol_ai_coach/
├── docs/
│   └── lol_coach_architecture.md   ← 지금 이 파일 (전체 지도)
│
├── backend/
│   └── app/
│       ├── core/       → DB 엔진, 인증, 설정          [SPEC](../backend/app/core/SPEC.md)
│       ├── models/     → SQLAlchemy ORM 모델           [SPEC](../backend/app/models/SPEC.md)
│       ├── parser/     → .rofl 파싱 + Resilience       [SPEC](../backend/app/parser/SPEC.md)
│       ├── analysis/   → 9개 분석 엔진 + 파이프라인    [SPEC](../backend/app/analysis/SPEC.md)
│       ├── layer/      → Layer 1~4 생성기              [SPEC](../backend/app/layer/SPEC.md)
│       ├── coaching/   → LLM 프롬프트 + 스크립트       [SPEC](../backend/app/coaching/SPEC.md)
│       ├── benchmark/  → 챌린저 통계 수집              [SPEC](../backend/app/benchmark/SPEC.md)
│       ├── workers/    → Celery 분석 작업              [SPEC](../backend/app/workers/SPEC.md)
│       └── api/        → FastAPI 라우터                [SPEC](../backend/app/api/SPEC.md)
│
├── frontend/           → Next.js 웹 대시보드           [SPEC](../frontend/SPEC.md)
├── desktop/            → Electron 오버레이 앱          [SPEC](../desktop/SPEC.md)
└── infra/              → Docker, CI/CD, 배포           [SPEC](../infra/SPEC.md)
```

---

## 시스템 흐름 (한눈에)

```
[유저 PC]
  └─ Electron 앱 → .rofl 파일 탐지 → S3 Presigned URL 직접 업로드
                                              ↓
[API Server (FastAPI)]
  └─ POST /api/analysis/{id}/start → Celery 큐 투입
                                              ↓
[Analysis Worker (Celery)]
  ├─ 1. S3에서 .rofl 다운로드
  ├─ 2. 파싱 (FULL → PARTIAL → FALLBACK 자동 폴백)
  ├─ 3. 분석 파이프라인 (9개 엔진, 3단계 병렬)
  ├─ 4. Layer 1~4 생성
  ├─ 5. LLM 코칭 스크립트 생성
  ├─ 6. PlayerModel 업데이트 (DB)
  └─ 7. 결과 저장 + S3 원본 삭제

[실시간 진행률]
  └─ Redis Pub/Sub → WebSocket → 브라우저/앱

[유저]
  └─ 웹 대시보드: 분석 리포트 열람 + 대화형 코칭 (LLM)
  └─ 데스크탑 오버레이: 리플레이 재생 중 코칭 텍스트 동기화
```

---

## 분석 파이프라인 (3단계)

```
Stage 1 (병렬) ─────────────────────────────────────────────
  WaveEngine      웨이브 상태 (FAST_PUSH/FREEZE/LOSING_WAVE 등)
  TempoEngine     리콜 타이밍 + 파워 스파이크
  MacroEngine     오브젝트/타워/사이드 판단
  CompositionAnalyzer  팀 조합 아키타입 + 구간별 유불리
  GameStateEngine 게임 국면 (AHEAD/EVEN/BEHIND/SNOWBALL/COMEBACK)
  [JungleEngine]  (정글러 역할 시 추가)

Stage 2 (직렬, wave_timeline 의존) ─────────────────────────
  CombatEngine    킬각/죽을각 판단 + 교전 시뮬레이션

Stage 3 (병렬, fight_verdicts 의존) ─────────────────────────
  PredictiveEngine   갱 위험 / 오브젝트 창 예측
  IntentEngine       플레이어 의도 추론 (WRONG_INTENT vs WRONG_EXECUTION)
```

---

## 데이터 품질 등급

| 등급 | 조건 | 가능한 분석 |
|------|------|------------|
| FULL | .rofl 완전 파싱 | 모든 엔진 |
| PARTIAL | .rofl 메타 + Riot API 타임라인 | Combat(이벤트), Macro, GameState |
| FALLBACK | Riot API 타임라인만 (match_id만 있을 때) | 이벤트 분석 + LLM 기본 피드백 |

---

## 핵심 API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/auth/login` | 로그인 → JWT 발급 |
| POST | `/api/analysis/upload-url` | S3 업로드 URL 발급 |
| POST | `/api/analysis/{id}/start` | 분석 시작 (Celery 투입) |
| GET | `/api/analysis/{id}/status` | 진행률 조회 |
| GET | `/api/analysis/{id}/result` | 분석 결과 조회 |
| POST | `/api/analysis/{id}/chat` | 대화형 코칭 (SSE 스트리밍) |
| WS | `/api/analysis/ws/{id}` | 실시간 진행률 WebSocket |
| POST | `/api/analysis/fallback` | match_id만으로 분석 |

---

## 기술 스택 요약

| 영역 | 기술 |
|------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x (async) |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| LLM | Claude (Anthropic API) |
| Storage | AWS S3 |
| Frontend | Next.js 15, TypeScript, Tailwind CSS |
| Desktop | Electron |
| Deploy | AWS ECS (Fargate), Vercel, GitHub Actions |

---

## 보안 원칙

- **Riot ToS 준수**: Riot API 원본 응답 저장 금지. 집계 통계만 저장.
- **LCU API**: 유저 로컬 환경에서만 사용. 서버 자동화 절대 금지.
- **JWT**: Access Token 1시간, Refresh Token 30일 HttpOnly 쿠키.
- **S3**: Presigned URL 5분 유효. 분석 완료 즉시 삭제.
- **분석 워커**: 외부 인터넷 Egress 차단 (악성 .rofl 방어).
- **CORS**: `*` 허용 금지. 화이트리스트 오리진만.

---

## ADR 요약 (주요 설계 결정)

| ADR | 결정 | 이유 |
|-----|------|------|
| 001 | 분석 파이프라인 3단계 병렬화 | 의존성 있는 엔진은 직렬, 독립 엔진은 병렬 → 전체 시간 단축 |
| 002 | PlayerModel = SQLAlchemy ORM JSON 컬럼 | ORM 쿼리 표현식 필요, 복합 필드는 JSON으로 유연하게 저장 |
| 003 | WaveEngine 5초 샘플링 | 54,000 스냅샷 전체 처리 시 성능 문제 → 360개 샘플로 충분 |
| 004 | Refresh Token HttpOnly 쿠키 | XSS로 AT 탈취 시 피해 1시간 한정. RT는 JS 접근 불가 |
| 005 | S3 직접 업로드 (Presigned URL) | 서버 대역폭 절약. 파일이 서버를 거치지 않음 |
| 006 | 분석 워커 네트워크 격리 | 악성 .rofl 파일의 외부 연결 시도 차단 |
| 007 | BenchmarkStat 리전별 분리 | KR/EUW 플레이 스타일 차이로 혼합 시 수치 왜곡 |
| 008 | LLM 응답 사실 검증 (2회 재시도) | 잘못된 수치 코칭은 신뢰도 저하 → Layer2와 대조 후 교정 |
| 009 | SELECT FOR UPDATE (PlayerModel) | 동시 경기 분석 완료 시 경쟁 조건 방지 |
| 010 | .rofl 3단계 Resilience 폴백 | 패치마다 포맷 변경 가능성 → Riot API로 자동 폴백 |
