# Parser Module — SPEC

> `backend/app/parser/`  
> .rofl 바이너리 파싱 + 파싱 실패 시 Riot API 타임라인 폴백 (Resilience Layer)

## 구현 진행 상황

| 파일 | 상태 | 비고 |
|------|------|------|
| `models.py` | ✅ 완료 | ParseResult, ValidationReport |
| `validator.py` | ✅ 완료 | 타임스탬프/좌표 검증 |
| `metadata.py` | ✅ 완료 | .rofl 헤더 JSON 추출 |
| `chunk_decoder.py` | ✅ 완료 | zstd/zlib 청크 디코딩 |
| `rofl_parser.py` | ✅ 완료 | 메인 파서 (암호화 청크는 TODO) |
| `resilience.py` | ✅ 완료 | 3단계 폴백 오케스트레이션 (동기) |

> 마지막 업데이트: 2026-04-10

## SPEC 수정 이력

- `parse_with_fallback`: `async` → **동기** 메서드로 변경 (Celery 워커는 동기 컨텍스트, asyncio.run() 오버헤드 제거)
- `RoflVersionMismatch` 예외 클래스 정의 추가 (models.py에 위치)
- `riot_client`: `from app.benchmark.riot_client import RiotApiClient` 경로 명시
- Magic bytes: `b"RIOT\x00\x00"` (6바이트, 앞 4바이트 `RIOT` + 버전 2바이트) — 실제 파일 시그니처
- `chunk_decoder.py` 상세 내용 추가

---

## 파일 목록

```
parser/
├── rofl_parser.py        # .rofl 바이너리 파싱 메인
├── metadata.py           # 메타데이터 헤더 추출 (parse_metadata_only)
├── chunk_decoder.py      # 압축 청크 디코딩 (zstd/zlib)
├── resilience.py         # RoflResilienceLayer — 폴백 오케스트레이션
├── validator.py          # DataValidator — 파싱 결과 일관성 검증
└── models.py             # ParseResult, ValidationReport 데이터클래스
```

---

## 데이터 품질 등급

| 등급 | 상황 | 가능한 분석 |
|------|------|------------|
| FULL | .rofl 완전 파싱 | 모든 엔진 (Combat/Wave/Macro/Predictive) |
| PARTIAL | 메타데이터 + Riot API 타임라인 | Combat(이벤트), Macro(이벤트), GameState |
| FALLBACK | Riot API 타임라인만 | 이벤트 목록 + LLM 기본 피드백 |

---

## models.py

```python
from dataclasses import dataclass, field

@dataclass
class ParseResult:
    """
    파싱 결과 통합 컨테이너.
    snapshots: {timestamp_ms: snap_dict}
               snap_dict = {players, wards, minions, towers, events}
    events:    [{timestamp, type, data}]
    quality:   "FULL" | "PARTIAL" | "FALLBACK"
    metadata:  champion_id, player_id, puuid, match_id, patch, region 등
    """
    events: list[dict]
    snapshots: dict                      # {int: dict}, FALLBACK 시 {}
    quality: str = "FALLBACK"
    metadata: dict = field(default_factory=dict)

@dataclass
class ValidationReport:
    issues: list[str]
    is_valid: bool
```

---

## rofl_parser.py

### .rofl 바이너리 포맷

```
[Magic: 6 bytes "RIOT00"]
[Header Length: 4 bytes LE]
[File Length:   4 bytes LE]
[Chunk Headers: N × {chunk_id, type, length, next_chunk_id, offset}]
[Metadata JSON Block]
[Chunk Data Blocks (zstd/zlib compressed)]
```

### 스냅샷 샘플링 전략

| 저장 단위 | 샘플링 | 용도 |
|-----------|--------|------|
| 이벤트 로그 | 이벤트 발생 시점만 | 킬, 데스, 스킬, 와드 |
| 1초 스냅샷 | 1초 간격 | 시야 분석, 동선 추적 |
| 분 단위 요약 | 1분 간격 | CS/골드/레벨 추이 |

> 전체 틱(30/초 × 1800s = 54,000) 저장 금지 — 메모리/성능 문제

### 스냅샷 dict 스키마

```python
snap = {
    "timestamp_ms": int,
    "players": [
        {
            "id": int,
            "puuid": str,
            "team": "blue" | "red",
            "champion_name": str,
            "role": str,
            "position": {"x": float, "y": float},
            "hp": float,
            "max_hp": float,
            "level": int,
            "gold": int,
            "cs": int,
            "base_ad": float,
            "bonus_ad": float,
            "ap": float,
            "armor": float,
            "magic_resist": float,
            "lethality": float,
            "items": [int],          # item ID 목록
            "spells": [{"id": str, "cooldown": float}],
            "is_visible": bool,
        }
    ],
    "wards": [
        {"position": {"x": float, "y": float}, "type": str, "owner": int, "ttl": int}
    ],
    "minions": [
        {"position": {"x": float, "y": float}, "team": "blue" | "red", "type": str}
    ],
    "towers": [
        {"position": {"x": float, "y": float}, "team": str, "hp": float, "max_hp": float}
    ],
    "events": [
        {"timestamp": int, "type": str, "data": dict}
    ],
    # 편의 필드 (파싱 시 집계)
    "dragon_spawn_in_ms": int | None,
    "my_team": "blue" | "red",
}
```

---

## resilience.py

```python
class RoflResilienceLayer:
    """
    3단계 폴백 전략:
    1. .rofl 완전 파싱 → FULL
    2. 메타데이터 + Riot API 타임라인 병합 → PARTIAL
    3. Riot API 타임라인 단독 → FALLBACK

    주의: Celery 동기 컨텍스트에서 실행 → 모든 메서드 동기
    Riot API 호출은 httpx.Client (동기) 사용
    """

    def parse_with_fallback(self, rofl_path: str, match_id: str) -> ParseResult:  # 동기
        # 1단계: 완전 파싱
        try:
            result = await self._parse_rofl_full(rofl_path)
            result.quality = "FULL"
            return result
        except RoflVersionMismatch:
            pass   # 패치로 포맷 변경 → PARTIAL 시도
        except Exception:
            pass   # 파일 손상 → PARTIAL 시도

        # 2단계: 메타데이터 + 타임라인
        try:
            meta = parse_metadata_only(rofl_path)
            timeline = await riot_client.get_match_timeline(match_id)
            result = self._merge_meta_and_timeline(meta, timeline)
            result.quality = "PARTIAL"
            return result
        except Exception:
            pass

        # 3단계: 타임라인 단독
        timeline = await riot_client.get_match_timeline(match_id)
        return self._timeline_to_parse_result(timeline)   # quality = "FALLBACK"

    def _timeline_to_parse_result(self, timeline: dict) -> ParseResult:
        """Riot API 타임라인 → ParseResult 변환. snapshots = {} (위치 없음)"""
        events = [
            {"timestamp": e["timestamp"], "type": e["type"], "data": e}
            for frame in timeline["info"]["frames"]
            for e in frame["events"]
        ]
        return ParseResult(events=events, snapshots={}, quality="FALLBACK")
```

---

## validator.py

```python
class DataValidator:
    def validate(self, result: ParseResult) -> ValidationReport:
        issues = []

        # 타임스탬프 연속성 (>5초 갭 감지)
        times = sorted(result.snapshots.keys())
        gaps = [t2 - t1 for t1, t2 in zip(times, times[1:]) if t2 - t1 > 5000]
        if gaps:
            issues.append(f"타임스탬프 갭 {len(gaps)}개 (최대 {max(gaps)/1000:.1f}초)")

        # 좌표 범위 (맵 외곽 이상 감지)
        for snap in result.snapshots.values():
            for player in snap.get("players", []):
                x = player["position"]["x"]
                y = player["position"]["y"]
                if not (0 <= x <= 15000 and 0 <= y <= 15000):
                    issues.append(f"비정상 좌표: ({x:.0f}, {y:.0f})")

        return ValidationReport(issues=issues, is_valid=len(issues) == 0)
```

---

## metadata.py

```python
def parse_metadata_only(rofl_path: str) -> dict:
    """
    .rofl 전체 파싱 없이 헤더 메타데이터만 빠르게 추출.
    반환: {match_id, game_version, game_length, participants: [...], ...}
    청크 데이터 디코딩 없이 헤더 오프셋 직접 접근 → 파싱 실패율 낮음
    """
```

---

## .rofl 파일 자동 탐지

```python
ROFL_DEFAULT_PATHS = [
    r"C:\Riot Games\League of Legends\Replays",
    r"D:\Riot Games\League of Legends\Replays",
]

def read_registry_install_path() -> str | None:
    """
    HKLM\SOFTWARE\Riot Games\League of Legends 레지스트리에서 설치 경로 읽기.
    Windows 아닌 환경(CI 등)은 즉시 None 반환.
    3개 레지스트리 경로 순차 시도 → 모두 실패 시 None.
    """

def find_rofl_files() -> list[Path]:
    """최근 20개 .rofl 파일 반환 (수정 시간 내림차순)"""
    install_path = read_registry_install_path()
    registry_paths = [Path(install_path) / "Replays"] if install_path else []
    paths = registry_paths + [Path(p) for p in ROFL_DEFAULT_PATHS]
    results = []
    for base in paths:
        if base.exists():
            results.extend(sorted(base.glob("*.rofl"), key=lambda p: p.stat().st_mtime, reverse=True))
    return results[:20]
```
