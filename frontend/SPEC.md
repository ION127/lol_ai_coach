# Frontend — SPEC

> `frontend/`  
> Next.js 15 (App Router) + TypeScript. 분석 리포트 뷰어 + 대화형 코칭 UI.

---

## 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| Framework | Next.js 15 (App Router) | SSR/SSG + API Routes |
| Language | TypeScript | 타입 안전성 |
| Styling | Tailwind CSS | 빠른 UI 구성 |
| State | Zustand | 경량, 단순 |
| Data Fetching | TanStack Query | 캐싱 + 재시도 |
| Charts | Recharts | 골드/CS 추이 시각화 |
| Deploy | Vercel | Next.js 최적화 배포 |

---

## 폴더 구조

```
frontend/
├── src/
│   ├── app/                     # Next.js App Router
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx
│   │   │   └── register/page.tsx
│   │   ├── dashboard/page.tsx   # 분석 목록 + 업로드
│   │   ├── analysis/
│   │   │   └── [id]/
│   │   │       ├── page.tsx     # 분석 결과 리포트
│   │   │       └── chat/page.tsx # 대화형 코칭
│   │   ├── layout.tsx
│   │   └── globals.css
│   │
│   ├── components/
│   │   ├── upload/
│   │   │   ├── RoflUploader.tsx    # 드래그&드랍 + 진행률
│   │   │   └── AnalysisProgress.tsx # WebSocket 진행률 바
│   │   ├── report/
│   │   │   ├── ReportHeader.tsx    # 경기 요약 (KDA/CS/시간)
│   │   │   ├── MistakeList.tsx     # 핵심 실수 목록
│   │   │   ├── TimelineViewer.tsx  # 이벤트 타임라인
│   │   │   ├── GoldChart.tsx       # 골드 격차 추이 차트
│   │   │   └── FocusTasks.tsx      # 다음 3게임 집중 과제
│   │   ├── chat/
│   │   │   ├── ChatWindow.tsx      # 대화창 (SSE 스트리밍)
│   │   │   └── ChatInput.tsx       # 질문 입력
│   │   └── common/
│   │       ├── Navbar.tsx
│   │       └── LoadingSpinner.tsx
│   │
│   ├── lib/
│   │   ├── api.ts               # fetchWithAuth + uploadRofl + subscribeToProgress
│   │   ├── auth.ts              # 토큰 관리 (localStorage + 쿠키)
│   │   └── utils.ts             # 날짜 포맷, 숫자 포맷 등
│   │
│   └── store/
│       ├── authStore.ts         # 로그인 상태
│       └── analysisStore.ts     # 현재 분석 상태
```

---

## lib/api.ts — 핵심 함수

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * JWT 자동 첨부 + 401 시 토큰 갱신 후 1회 재시도.
 * _retryCount로 무한루프 방지 (최대 1회 재시도).
 */
export async function fetchWithAuth(
  path: string,
  options: RequestInit = {},
  _retryCount = 0
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",   // Refresh Token 쿠키 자동 전송
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (res.status === 401 && _retryCount === 0) {
    // Access Token 만료 → Refresh Token으로 갱신 시도
    const refreshed = await refreshAccessToken();
    if (refreshed) return fetchWithAuth(path, options, 1);
    // 갱신 실패 → 로그아웃
    authStore.getState().logout();
  }
  return res;
}

/**
 * S3 Presigned URL로 직접 업로드 (서버 경유 없음 — 대역폭 절약).
 * onProgress: 업로드 진행률 콜백 (0~100).
 */
export function uploadRofl(
  uploadUrl: string,
  file: File,
  onProgress?: (pct: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");

    if (onProgress) {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      });
    }
    xhr.onload  = () => (xhr.status === 200 ? resolve() : reject(new Error(`Upload failed: ${xhr.status}`)));
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
}

/**
 * WebSocket으로 분석 진행률 구독.
 * 지수 백오프 재연결 (1s, 2s, 4s, 8s, 최대 5회).
 */
export function subscribeToProgress(
  analysisId: string,
  onMessage: (msg: ProgressMessage) => void,
  onDone: () => void
): () => void {
  let retries = 0;
  let ws: WebSocket;

  function connect() {
    ws = new WebSocket(`${WS_BASE}/api/analysis/ws/${analysisId}`);
    ws.onmessage = (e) => {
      const msg: ProgressMessage = JSON.parse(e.data);
      onMessage(msg);
      if (msg.type === "complete" || msg.type === "error") {
        onDone();
        ws.close();
      }
    };
    ws.onclose = () => {
      if (retries < 5) {
        setTimeout(connect, Math.min(1000 * 2 ** retries, 8000));
        retries++;
      }
    };
  }
  connect();
  return () => ws?.close();   // cleanup 함수
}
```

---

## 주요 페이지 흐름

### 업로드 → 분석 → 리포트

```
1. /dashboard
   - 최근 .rofl 파일 목록 (Electron 앱에서 감지, 웹에서는 파일 선택)
   - 파일 선택 → POST /api/analysis/upload-url → Presigned URL 획득
   - S3 직접 업로드 (uploadRofl + onProgress)
   - POST /api/analysis/{id}/start → Celery 큐 투입
   - WebSocket 연결 (subscribeToProgress) → 진행률 실시간 표시

2. /analysis/{id}
   - GET /api/analysis/{id}/result → 분석 결과 로드
   - ReportHeader: KDA/CS/골드/시야 수치
   - MistakeList: 핵심 실수 (타임코드 클릭 → 리플레이 오버레이 이동)
   - GoldChart: 분 단위 골드 격차 추이
   - FocusTasks: 다음 3게임 집중 과제

3. /analysis/{id}/chat
   - 자유 질문 입력 → POST /api/analysis/{id}/chat → SSE 스트리밍
   - 대화 히스토리 유지 (클라이언트 메모리)
```

---

## 인증 흐름

```
로그인 → access_token → localStorage (1시간 만료)
        refresh_token → HttpOnly 쿠키 (30일, JS 접근 불가)

API 호출 → Authorization: Bearer {access_token}
401 수신 → POST /api/auth/refresh (쿠키 자동 전송) → 새 access_token
갱신 실패 → localStorage 클리어 → /login 리다이렉트
```

---

## 환경변수

```env
NEXT_PUBLIC_API_URL=https://api.lol-ai-coach.com
NEXT_PUBLIC_WS_URL=wss://api.lol-ai-coach.com
```
