# API Module — SPEC

> `backend/app/api/`  
> FastAPI 라우터. 인증, 분석 시작/상태 조회, 대화형 코칭, 벤치마크 조회.

## 구현 진행 상황

| 파일 | 상태 | 테스트 | 비고 |
|------|------|--------|------|
| `auth.py` | ✅ 완료 | 17/17 통과 | register/login/refresh/logout/me |
| `analysis.py` | ✅ 완료 | 17/17 통과 | upload-url/start/status/result/history/fallback |
| `chat.py` | ⬜ 미구현 | — | SSE 스트리밍 |
| `benchmark.py` | ⬜ 미구현 | — | 챌린저 벤치마크 조회 |
| `summoner.py` | ⬜ 미구현 | — | Riot API 프록시 |
| `websocket_manager.py` | ⬜ 미구현 | — | WS + Redis Pub/Sub |

> 마지막 업데이트: 2026-04-10

---

## 파일 목록

```
api/
├── auth.py              # 회원가입/로그인/토큰 갱신/로그아웃
├── analysis.py          # 업로드 URL 발급 / 분석 시작 / 상태 조회
├── chat.py              # 대화형 코칭 (SSE 스트리밍)
├── benchmark.py         # 챌린저 벤치마크 조회
├── summoner.py          # 소환사 정보 조회 (Riot API 프록시)
└── websocket_manager.py # WebSocket 연결 관리자 + Redis Pub/Sub 브릿지
```

---

## auth.py

### 엔드포인트

```
POST /api/auth/register   → 회원가입
POST /api/auth/login      → 로그인 (Access Token + Refresh Token 쿠키)
POST /api/auth/refresh    → Access Token 갱신
POST /api/auth/logout     → Refresh Token 폐기
```

```python
@router.post("/login")
async def login(body: LoginRequest, response: Response, db=Depends(get_db_session)):
    user = await _authenticate(body.email, body.password, db)
    access_token  = create_access_token(user.id)
    refresh_token = _create_refresh_token(user, db)

    # Refresh Token → HttpOnly Secure 쿠키 (XSS 방어)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=30 * 24 * 3600,  # 30일
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/refresh")
async def refresh_token(
    refresh_token: str = Cookie(None),
    db=Depends(get_db_session)
):
    """
    Refresh Token Rotation:
    - 이전 토큰 즉시 폐기 → 새 토큰 발급
    - 탈취된 토큰 재사용 감지 시 모든 세션 강제 로그아웃
    """
```

---

## analysis.py

### 엔드포인트

```
POST /api/analysis/upload-url           → S3 Presigned URL 발급
POST /api/analysis/{id}/start           → 분석 시작 (Celery 큐 투입)
GET  /api/analysis/{id}/status          → 분석 상태/진행률 조회
GET  /api/analysis/{id}/result          → 분석 결과 조회
GET  /api/analysis/history              → 내 분석 목록
POST /api/analysis/fallback             → match_id만으로 분석 (FALLBACK 품질)
WS   /api/analysis/ws/{id}             → 실시간 진행률 WebSocket
```

```python
@router.post("/upload-url")
async def get_upload_url(
    body: UploadUrlRequest,   # {"filename": "...", "file_size": int}
    current_user = Depends(get_current_user),
    db = Depends(get_db_session),
):
    """
    S3 Presigned URL 발급.
    - 5분 유효
    - content-length-range 조건 포함 (최대 120MB)
    - 유저별 격리: s3://bucket/{user_id}/{analysis_id}.rofl
    """
    validate_upload_request(body.filename, body.file_size, current_user.id)
    analysis_id = f"anal_{uuid4().hex[:12]}"
    upload_url  = generate_presigned_url(
        key=f"{current_user.id}/{analysis_id}.rofl",
        conditions=[["content-length-range", 0, 120 * 1024 * 1024]],
        expires_in=300,
    )
    # AnalysisRecord 생성 (status="pending")
    record = AnalysisRecord(id=analysis_id, user_id=current_user.id, ...)
    db.add(record)
    return {"upload_url": upload_url, "analysis_id": analysis_id}


@router.post("/{analysis_id}/start")
async def start_analysis(
    analysis_id: str,
    body: StartAnalysisRequest,   # {"match_id": str, "champion_id": int, ...}
    current_user = Depends(get_current_user),
    db = Depends(get_db_session),
):
    """
    Celery 큐 투입.
    - 소유권 확인 (record.user_id == current_user.id)
    - 중복 제출 방지: Redis "submitted:{analysis_id}" 키 확인
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if not record or record.user_id != current_user.id:
        raise HTTPException(404, "Analysis not found")

    run_analysis.delay(analysis_id, record.s3_key)
    return {"status": "queued"}


@router.get("/{analysis_id}/status")
async def get_status(analysis_id: str, current_user=Depends(get_current_user), db=Depends(get_db_session)):
    """
    DB 상태 + Redis 진행률 퍼센트 병합.
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if not record or record.user_id != current_user.id:
        raise HTTPException(404)
    pct = redis_client.get(f"analysis_progress_pct:{analysis_id}")
    return {
        "status": record.status,
        "progress_pct": int(pct) if pct else 0,
        "data_quality": record.data_quality,
        "error": record.error_message,
    }
```

---

## chat.py

```python
@router.post("/{analysis_id}/chat")
async def chat(
    analysis_id: str,
    body: ChatRequest,   # {"question": str, "history": [...]}
    current_user = Depends(get_current_user),
    db = Depends(get_db_session),
):
    """
    SSE(Server-Sent Events) 스트리밍 응답.
    분석 결과(layers)를 컨텍스트로 LLM에 전달.
    """
    record = await db.get(AnalysisRecord, analysis_id)
    if not record or record.user_id != current_user.id:
        raise HTTPException(404)
    if record.status != "complete":
        raise HTTPException(400, "Analysis not complete")

    layers = _load_layers_from_record(record)

    async def event_stream():
        async for chunk in chat_handler.chat(body.question, analysis_id, body.history, layers):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

---

## websocket_manager.py

```python
class AnalysisConnectionManager:
    """
    {analysis_id: set[WebSocket]} 맵 유지.
    Redis Pub/Sub → WebSocket 브릿지.
    """

    async def connect(self, ws: WebSocket, analysis_id: str): ...
    async def disconnect(self, ws: WebSocket, analysis_id: str): ...
    async def broadcast(self, analysis_id: str, message: dict): ...

manager = AnalysisConnectionManager()

@router.websocket("/ws/{analysis_id}")
async def ws_analysis_progress(ws: WebSocket, analysis_id: str):
    """
    연결 즉시 현재 상태 동기화 (재연결 지원).
    Redis Pub/Sub 구독 → 메시지 수신 시 클라이언트에 전달.
    "complete" 또는 "error" 메시지 수신 시 연결 종료.

    클라이언트 재연결 전략: 지수 백오프 (1s, 2s, 4s, 8s, max 5회)
    """
```

---

## 보안 설계

### Rate Limiting
```python
RATE_LIMITS = {
    "/api/analysis/upload-url": "20/hour",   # 남용 방지
    "/api/analysis/{id}/chat":  "60/hour",   # LLM 크레딧 보호
    "/api/auth/login":          "10/minute", # 브루트포스 방어
    "default":                  "200/minute",
}
```

### 업로드 보안
```python
UPLOAD_LIMITS = {
    "max_file_size_mb": 120,
    "allowed_extensions": [".rofl"],
    "s3_prefix_isolation": True,   # {user_id}/ 격리
}
# Presigned URL에 content-length-range 조건 포함 → S3 수준 강제
```

### CORS
```python
ALLOWED_ORIGINS = [
    "https://lol-ai-coach.com",
    "https://www.lol-ai-coach.com",
    "http://localhost:3000",
]
# "*" 절대 금지 — JWT 쿠키 노출 위험
```

---

## Health Check

```
GET /health   → {"status": "ok"}  (liveness probe)
GET /ready    → DB + Redis + Celery 상태 확인 (readiness probe)
```
