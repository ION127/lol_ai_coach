# Desktop App — SPEC

> `desktop/`  
> Electron (또는 Tauri) 데스크탑 앱.  
> .rofl 파일 자동 탐지 + 업로드 + 리플레이 오버레이 코칭.

---

## 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| Framework | Electron | Windows 네이티브 API (레지스트리, 오버레이) |
| UI | Next.js (embedded) or React | 웹 컴포넌트 재사용 |
| IPC | Electron contextBridge | 렌더러-메인 안전한 통신 |
| 배포 | electron-builder | NSIS 인스톨러 (Windows) |

> **Tauri 대안**: Rust 기반, 번들 크기 작음. 레지스트리 접근 가능하나 생태계 성숙도 낮음.  
> 현재는 Electron 선택 (Windows API 안정성 우선).

---

## 폴더 구조

```
desktop/
├── src/
│   ├── main/
│   │   ├── main.ts            # Electron 메인 프로세스
│   │   ├── rofl_watcher.ts    # .rofl 폴더 감시 (chokidar)
│   │   ├── registry.ts        # Windows 레지스트리 접근
│   │   └── overlay.ts         # 리플레이 오버레이 창 관리
│   │
│   └── renderer/
│       ├── app.tsx            # 렌더러 React 앱
│       ├── pages/
│       │   ├── FileList.tsx   # 최근 .rofl 목록
│       │   └── Settings.tsx   # API URL 설정 등
│       └── overlay/
│           ├── CoachOverlay.tsx  # 리플레이 위 코칭 텍스트
│           └── ScriptPlayer.tsx # 타임코드 동기화 재생
```

---

## 핵심 기능

### 1. .rofl 파일 자동 탐지

```typescript
// registry.ts
import { execSync } from "child_process";

export function readRegistryInstallPath(): string | null {
  try {
    const keys = [
      "HKLM\\SOFTWARE\\Riot Games\\League of Legends",
      "HKLM\\SOFTWARE\\WOW6432Node\\Riot Games\\League of Legends",
      "HKCU\\SOFTWARE\\Riot Games\\League of Legends",
    ];
    for (const key of keys) {
      try {
        const out = execSync(
          `reg query "${key}" /v Location 2>nul`,
          { encoding: "utf-8" }
        );
        const match = out.match(/Location\s+REG_SZ\s+(.+)/);
        if (match) return match[1].trim();
      } catch {}
    }
    return null;
  } catch {
    return null;
  }
}

// rofl_watcher.ts
import chokidar from "chokidar";

const DEFAULT_PATHS = [
  "C:\\Riot Games\\League of Legends\\Replays",
  "D:\\Riot Games\\League of Legends\\Replays",
];

export function watchRoflFolder(onNewFile: (path: string) => void) {
  const installPath = readRegistryInstallPath();
  const watchPaths = [
    ...(installPath ? [`${installPath}\\Replays`] : []),
    ...DEFAULT_PATHS,
  ].filter((p) => require("fs").existsSync(p));

  const watcher = chokidar.watch(watchPaths, { persistent: true });
  watcher.on("add", (path) => {
    if (path.endsWith(".rofl")) onNewFile(path);
  });
  return watcher;
}
```

### 2. 리플레이 오버레이

```typescript
// overlay.ts
import { BrowserWindow, screen } from "electron";

let overlayWindow: BrowserWindow | null = null;

export function createOverlay() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  overlayWindow = new BrowserWindow({
    width: 400,
    height: 200,
    x: width - 420,
    y: 20,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  overlayWindow.loadURL("app://./overlay");
  overlayWindow.setIgnoreMouseEvents(true, { forward: true }); // 클릭 투과
}

export function updateOverlayContent(message: string, timestampSec: number) {
  overlayWindow?.webContents.send("coaching-update", { message, timestampSec });
}
```

### 3. 코칭 스크립트 재생 (타임코드 동기화)

```typescript
// ScriptPlayer.tsx
interface ScriptItem {
  timestamp_sec: number;
  type: "mistake" | "good" | "tip";
  title: string;
  body: string;
}

export function ScriptPlayer({ script }: { script: ScriptItem[] }) {
  const [currentTime, setCurrentTime] = useState(0);

  // 리플레이 시간 추적 (LCU API 또는 윈도우 타이틀 파싱)
  useEffect(() => {
    const timer = setInterval(() => {
      const t = getReplayCurrentTime();  // LCU API /lol-replay/v1/playback
      setCurrentTime(t);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 현재 시간과 일치하는 스크립트 아이템 표시 (±3초 허용)
  const current = script.find(
    (item) => Math.abs(item.timestamp_sec - currentTime) <= 3
  );

  if (!current) return null;
  return (
    <div className={`overlay-card ${current.type}`}>
      <h3>{current.title}</h3>
      <p>{current.body}</p>
    </div>
  );
}
```

---

## LCU API 연동 (리플레이 제어)

```typescript
// LCU API — 유저 로컬 환경에서만 사용 (서버 자동화 금지, Riot ToS §2.1)

async function getReplayCurrentTime(): Promise<number> {
  const res = await fetch("https://127.0.0.1:2999/playback", {
    // LCU API는 자체 서명 인증서 → rejectUnauthorized: false
    agent: new https.Agent({ rejectUnauthorized: false }),
  });
  const data = await res.json();
  return data.time;  // 현재 재생 시간 (초)
}

async function jumpToTimestamp(sec: number): Promise<void> {
  await fetch("https://127.0.0.1:2999/playback", {
    method: "POST",
    body: JSON.stringify({ time: sec }),
    agent: new https.Agent({ rejectUnauthorized: false }),
  });
}
```

---

## 배포 / 설치

```
# electron-builder 설정 (package.json)
"build": {
  "appId": "com.lol-ai-coach.app",
  "win": {
    "target": "nsis",
    "icon": "assets/icon.ico"
  },
  "nsis": {
    "oneClick": false,
    "allowToChangeInstallationDirectory": true
  }
}

배포 파일: LolAICoach-Setup-1.0.0.exe (~80MB)
자동 업데이트: electron-updater (GitHub Releases 또는 S3)
```

---

## 보안 고려사항

- LCU API: 로컬 전용, 서버에서 절대 호출 금지 (Riot ToS §2.1)
- 업로드: 유저가 직접 파일 선택 → S3 Presigned URL 직접 업로드 (서버 경유 없음)
- API 키 저장: electron-store (OS 키체인 연동) — 하드코딩 금지
