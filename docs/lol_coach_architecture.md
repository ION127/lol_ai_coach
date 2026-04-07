# LoL AI Coach — System Architecture & Technical Design

> League of Legends .rofl Replay Analysis & AI Coaching Service  
> Version 3.0 | 2026.04  
> ⚡ v2.0: Wave + Tempo + Macro Engine 추가  
> ⚡ v3.0: Predictive Layer + Game State Engine + Composition Analyzer + Player Modeling + Resilience Layer 추가

---

## Project Overview

| 항목 | 내용 |
|------|------|
| Project Name | LoL AI Coach (가칭) |
| Service Type | .rofl 리플레이 기반 AI 코칭 서비스 |
| Core Feature | 킬각/죽을각 + 웨이브/템포/매크로 + **예측/게임상태/조합/개인화** + 대화형 코칭 + 리플레이 오버레이 |
| Data Source | Riot API + .rofl 파일 + Data Dragon |
| Target User | 골드~다이아 티어 솔로랭크 유저 |
| Benchmark | 챌린저 TOP 100 플레이 데이터 |

---

## Table of Contents

**분석 파이프라인**
1. [System Overview — 전체 시스템 구조](#1-system-overview)
2. [Data Pipeline — 데이터 수집 및 처리](#2-data-pipeline)
3. [.rofl Parser + Resilience Layer — 파싱 엔진 + 신뢰성](#3-rofl-parser--resilience-layer) ⭐ v3.0
4. [Combat Analysis Engine — 킬각/죽을각 분석 엔진](#4-combat-analysis-engine)
5. [Wave Analysis Engine — 웨이브 관리 분석 엔진](#5-wave-analysis-engine)
6. [Tempo & Recall Engine — 템포/리콜 분석 엔진](#6-tempo--recall-engine)
7. [Macro Decision Engine — 매크로 판단 분석 엔진](#7-macro-decision-engine)

**v3.0 신규 엔진**
8. [Predictive Simulation Engine — 미래 예측 엔진](#8-predictive-simulation-engine) ⭐ NEW
9. [Game State Engine — 게임 국면 분석 엔진](#9-game-state-engine) ⭐ NEW
10. [Draft & Composition Analyzer — 조합/챔피언 이해 엔진](#10-draft--composition-analyzer) ⭐ NEW
11. [Intent Inference — 플레이어 의도 추론](#11-intent-inference) ⭐ NEW
12. [Player Modeling & Actionable Coaching — 개인화 코칭](#12-player-modeling--actionable-coaching) ⭐ NEW

**출력 시스템**
13. [Layer System — 계층적 데이터 정제 시스템](#13-layer-system)
14. [Coaching Script Generator — 코칭 스크립트 생성기](#14-coaching-script-generator)
15. [LLM Integration + Validation — AI 코치 + 검증 레이어](#15-llm-integration--validation) ⭐ v3.0
16. [Desktop App — 리플레이 오버레이 앱](#16-desktop-app)

**인프라/운영**
17. [Infrastructure — 인프라 및 배포 구조](#17-infrastructure)
18. [Development Roadmap — 개발 로드맵](#18-development-roadmap)
19. [Tech Stack — 기술 스택 요약](#19-tech-stack)
20. [API Design — 핵심 API 설계](#20-api-design)

---

## 1. System Overview

전체 시스템은 6개의 핵심 컴포넌트로 구성됩니다.

### 1.1 High-Level Architecture

```
[User] → Desktop App (Electron/Tauri)
    ↓
[API Gateway] → FastAPI (Python) + JWT Auth
    ↓ WebSocket (실시간 진행률)
[Analysis Pipeline — Celery Workers]
    ├── .rofl Downloader (LCU API + LoL Client)
    ├── .rofl Parser + Resilience Layer (파싱 실패 시 Riot API 폴백) ← v3.0
    │
    ├── ─── Prediction Layer (미래를 예측한다) ─────────────────── v3.0
    │   ├── Predictive Simulation Engine  (10~20초 미래 시뮬레이션)
    │   └── Game State Engine             (앞섬/비김/뒤짐 국면 분류)
    │
    ├── ─── Intelligence Layer (상황을 이해한다) ────────────────── v3.0
    │   ├── Draft & Composition Analyzer  (조합/매치업 이해)
    │   ├── Intent Inference              (플레이어 의도 추론)
    │   └── Player Modeling              (개인 약점 + 성장 추적)
    │
    ├── ─── Context Layer (왜 그 교전이 생겼는가?) ─────────────── v2.0
    │   ├── Wave Analysis Engine         (웨이브 상태, 라인 주도권)
    │   ├── Tempo & Recall Engine        (리콜 타이밍, 파워 스파이크)
    │   └── Macro Decision Engine        (사이드/오브젝트/한타 판단)
    │
    ├── ─── Combat Layer (교전에서 왜 졌는가?) ─────────────────── v1.0
    │   ├── Combat Analysis Engine       (데미지/킬각 계산)
    │   └── Vision Engine               (시야 장악도 분석)
    │
    ├── Layer Generator (L1~L4 계층적 데이터 정제)
    └── Coaching Script Generator (연출 스크립트)
    ↓
[LLM Coach + Validation Layer] → Claude API (검증 후 피드백 생성) ← v3.0
    ↓
[Storage]
    ├── PostgreSQL (유저, 분석 결과, 벤치마크, 플레이어 모델)
    ├── Redis (작업 큐, 캐시)
    └── S3/MinIO (.rofl 임시 저장)
```

> **버전별 핵심 차이**
> | 분석 질문 | v1.0 | v2.0 | v3.0 |
> |-----------|------|------|------|
> | 교전에서 왜 졌는가? | ✅ | ✅ | ✅ |
> | 왜 그 교전이 생겼는가? | ❌ | ✅ Wave + Macro | ✅ |
> | 리콜 타이밍이 적절했는가? | ❌ | ✅ Tempo | ✅ |
> | 10초 뒤 갱 당할 것인가? | ❌ | ❌ | ✅ Predictive |
> | 지금 게임이 이기고 있는가? | ❌ | ❌ | ✅ Game State |
> | 이 조합에서 내가 어떻게 해야 하나? | ❌ | ❌ | ✅ Composition |
> | 나의 반복적 실수 패턴이 뭔가? | ❌ | ❌ | ✅ Player Model |

### 1.2 Core Data Flow

유저가 소환사 이름을 입력하면 아래 순서로 처리됩니다.

| Step | 단계 | 설명 | 소요시간 |
|------|------|------|----------|
| 1 | Match ID 조회 | Riot API로 최근 랭크 매치 목록 획득 | 2초 |
| 2 | .rofl 다운로드 | LCU API로 리플레이 파일 자동 다운로드 | 30~60초 |
| 3 | .rofl 파싱 + Resilience | 틱 단위 데이터 추출, 실패 시 API 폴백 | 5~15초 |
| 4a | **Wave 분석** | 웨이브 상태 / 라인 주도권 / 미니언 손실 계산 | 1~2초 |
| 4b | **Tempo 분석** | 리콜 타이밍 / 파워 스파이크 / 템포 격차 평가 | 1~2초 |
| 4c | 전투 분석 | 킬각/죽을각 계산, 시야 장악 분석, 이벤트 감지 | 3~5초 |
| 4d | **Macro 판단** | 싸움/사이드/오브젝트 최적 선택 평가 | 1~2초 |
| 4e | **Predictive 시뮬레이션** | 주요 순간 10~20초 미래 예측, EV 계산 | 2~3초 |
| 4f | **Game State 분류** | 국면 분석, 스노우볼 곡선, 스케일링 판단 | 1초 |
| 4g | **Composition + Intent** | 조합 이해, 플레이어 의도 추론 | 1~2초 |
| 5 | Layer 생성 | 4단계 계층적 데이터 정제 (Temporal Context 포함) | 1~2초 |
| 6 | 코칭 스크립트 | 리플레이 연출 대본 생성 (Wave/Macro 씬 포함) | 1~2초 |
| 7 | Player Model 업데이트 | 개인 약점 DB 갱신, 다음 과제 생성 | 1초 |
| 8 | LLM 피드백 + 검증 | 분석 결과를 자연어 피드백으로 변환 + 수치 검증 | 5~10초 |
| 9 | 결과 전달 | 앱에 분석 데이터 + 스크립트 전송 | 1초 |

> 총 소요시간: 약 60~120초 (v3.0 엔진 추가로 약 8~15초 증가)

---

## 2. Data Pipeline

### 2.1 데이터 소스

| 데이터 소스 | 제공 데이터 | 비고 |
|-------------|-------------|------|
| Riot API | 매치 히스토리, 타임라인, 소환사 정보 | 공식 API Key 필요 |
| LCU API | .rofl 다운로드, 클라이언트 제어 | 로컬 클라이언트 실행 필요 |
| Data Dragon | 챔피언/아이템/룬 수치 (JSON) | 패치마다 자동 갱신 |
| LoL Wiki | 데미지 공식, 상호작용 규칙 | 공식 변경 시 수동 반영 |
| .rofl 파일 | 틱 단위 게임 상태 (30틱/초) | LCU API로 다운로드 |

### 2.2 .rofl 자동 다운로드 시스템

서버에서 VM(Windows 또는 Linux+Wine)에 롤 클라이언트를 설치하고, 전용 계정으로 자동 로그인하여 .rofl을 다운로드합니다. LCU API가 UI 없이 자동 로그인을 지원하므로 완전 자동화가 가능합니다.

```
LCU API 호출 흐름:
1. lockfile에서 포트 + 인증 토큰 읽기
2. POST /lol-replays/v1/rofls/{gameId}/download
3. 다운로드 완료 대기 (폴링)
4. Replays 폴더에서 .rofl 파일 수집
5. 파싱 후 원본 삭제
```

### 2.3 챌린저 벤치마크 수집 (24시간 자동화)

챌린저 TOP 100명의 데이터를 자동으로 수집하여 벤치마크 DB를 구축합니다.

```
자동 수집 주기:
- 챌린저 목록 갱신: 매일 1회 (Riot API league-v4)
- 새 경기 감지: 30분마다 (Riot API match-v5)
- .rofl 다운로드: 새 경기 감지 시 즉시
- 파싱 + DB 저장: 다운로드 완료 즉시

다운로드 속도: 경기당 ~7초 간격 → 하루 최대 ~12,000경기
```

### 2.4 패치 자동 갱신

```
패치 감지 → Data Dragon 최신 버전 확인
  → champion.json, item.json, runesReforged.json 다운로드
  → DB의 챔피언/아이템/룬 수치 테이블 갱신
  → 수치 변경: 자동 반영
  → 공식 변경(리워크 등): 알림 → 수동 업데이트
```

---

## 3. .rofl Parser + Resilience Layer

### 3.1 .rofl 파일 구조

.rofl 파일은 크게 두 부분으로 구성됩니다: 메타데이터(JSON)와 게임 청크 데이터(바이너리).

| 섹션 | 내용 | 비고 |
|------|------|------|
| Header | 파일 버전, 게임 버전, 암호화 키 | 고정 크기 |
| Metadata (JSON) | 플레이어 목록, 챔피언, KDA, CS 등 집계 통계 | ~50KB |
| Payload Header | 청크 개수, 키프레임 개수, 오프셋 정보 | 고정 크기 |
| Chunks | 틱 단위 게임 상태 (위치, 체력, 이벤트 등) | ~10~25MB |
| Keyframes | 주기적 전체 상태 스냅샷 | 복원 포인트 |

### 3.2 추출 데이터 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `timestamp` | int | 밀리초 단위 게임 시간 |
| `players[].champion_id` | int | 챔피언 ID |
| `players[].position` | {x, y} | 맵 좌표 (0~15000) |
| `players[].hp / max_hp` | int | 현재/최대 체력 |
| `players[].mana / max_mana` | int | 현재/최대 마나 |
| `players[].level` | int | 챔피언 레벨 (1~18) |
| `players[].items[]` | int[] | 보유 아이템 ID 목록 |
| `players[].gold` | int | 보유 골드 |
| `players[].cs` | int | CS (미니언 킬) |
| `players[].skills[]` | {id, level, cooldown} | 스킬 레벨 및 쿨다운 |
| `players[].spells[]` | {id, cooldown} | 소환사 주문 상태 |
| `events[]` | {type, ...} | 킬, 와드, 아이템 구매 등 |
| `wards[]` | {position, type, owner, ttl} | 와드 위치 및 남은 시간 |
| `minions[]` | {position, team, type} | 미니언 위치 |
| `towers[]` | {position, team, hp} | 타워 상태 |

### 3.3 파싱 전략

전체 틱(30/초 × 1800초 = 54,000틱)을 모두 저장하면 데이터가 너무 크므로, 용도별로 샘플링합니다.

| 저장 단위 | 샘플링 | 용도 |
|-----------|--------|------|
| 원본 DB | 모든 틱 (30/초) | 구체적 질문 대응 (Layer 4) |
| 이벤트 로그 | 이벤트 발생 시점만 | 킬, 데스, 스킬 사용, 와드 등 |
| 1초 스냅샷 | 1초 간격 (1/초) | 시야 분석, 동선 추적 |
| 분 단위 요약 | 1분 간격 | CS, 골드, 레벨 추이 |

### 3.4 Resilience Layer — .rofl 파싱 실패 대응 ⭐ v3.0

.rofl 포맷은 비공개 바이너리입니다. 패치마다 포맷이 바뀌거나 파일이 손상될 수 있으므로, **파싱 실패 시 Riot API Timeline으로 자동 폴백**합니다.

```python
class RoflResilienceLayer:
    """
    .rofl 파싱 실패 시 Riot API match-v5 타임라인으로 폴백
    
    데이터 품질 등급:
      FULL  — .rofl 완전 파싱 (틱 데이터 + 이벤트 + 미니언 위치)
      PARTIAL — .rofl 부분 파싱 (메타데이터 + 이벤트만)
      FALLBACK — Riot API 타임라인만 (1분 단위, 위치 없음)
    """
    
    async def parse_with_fallback(self, rofl_path: str, match_id: str) -> ParseResult:
        # 1. .rofl 완전 파싱 시도
        try:
            result = await self.rofl_parser.parse_file(rofl_path)
            result.quality = "FULL"
            return result
        except RoflVersionMismatch as e:
            logger.warning(f"[Resilience] .rofl 포맷 불일치 ({e}), 부분 파싱 시도")
        except Exception as e:
            logger.error(f"[Resilience] .rofl 파싱 실패 ({e}), API 폴백")
        
        # 2. 메타데이터만 추출 (부분 파싱)
        try:
            meta = parse_metadata_only(rofl_path)
            timeline = await riot_client.get_match_timeline(match_id)
            result = self._merge_meta_and_timeline(meta, timeline)
            result.quality = "PARTIAL"
            return result
        except Exception:
            pass
        
        # 3. Riot API 타임라인 전용 (최후 수단)
        timeline = await riot_client.get_match_timeline(match_id)
        result = self._timeline_to_parse_result(timeline)
        result.quality = "FALLBACK"
        logger.warning(f"[Resilience] FALLBACK 모드로 분석 진행 (match {match_id})")
        return result
    
    def _timeline_to_parse_result(self, timeline: dict) -> ParseResult:
        """
        Riot API 타임라인 → ParseResult 변환
        
        타임라인은 1분 단위 / 위치 정보 없음 / 미니언 수 없음
        → Wave 분석 불가, Combat 시뮬레이션 제한, 이벤트 기반 분석만 가능
        """
        events = []
        for frame in timeline["info"]["frames"]:
            for event in frame["events"]:
                events.append({
                    "timestamp": event["timestamp"],
                    "type": event["type"],
                    "data": event,
                })
        return ParseResult(events=events, snapshots={}, quality="FALLBACK")

class DataValidator:
    """파싱된 데이터 일관성 검증"""
    
    def validate(self, result: ParseResult) -> ValidationReport:
        issues = []
        
        # 타임스탬프 연속성 검증
        times = sorted(result.snapshots.keys())
        gaps = [t2 - t1 for t1, t2 in zip(times, times[1:]) if t2 - t1 > 5000]
        if gaps:
            issues.append(f"타임스탬프 갭 {len(gaps)}개 발견 (최대 {max(gaps)/1000:.1f}초)")
        
        # 좌표 범위 검증 (맵 외곽 좌표 이상 감지)
        for snap in result.snapshots.values():
            for player in snap.get("players", []):
                x, y = player["position"]["x"], player["position"]["y"]
                if not (0 <= x <= 15000 and 0 <= y <= 15000):
                    issues.append(f"비정상 좌표: ({x}, {y})")
        
        return ValidationReport(issues=issues, is_valid=len(issues) == 0)
```

#### 3.4.1 데이터 품질에 따른 분석 범위

| 품질 | .rofl 파싱 상태 | 가능한 분석 | 불가능한 분석 |
|------|----------------|-------------|---------------|
| FULL | 완전 파싱 | 모든 엔진 (Combat/Wave/Macro/Predictive) | 없음 |
| PARTIAL | 메타 + 이벤트 | Combat (이벤트 기반), Macro (이벤트 기반) | Wave (미니언 위치 없음) |
| FALLBACK | Riot API 타임라인 | 이벤트 목록 + LLM 기본 피드백 | Wave/Combat 시뮬레이션 |

---

## 4. Combat Analysis Engine

킬각/죽을각 분석의 핵심 엔진입니다. .rofl에서 추출한 데이터 + Data Dragon의 게임 수치를 결합하여, 매 시점에서의 교전 결과를 수학적으로 계산합니다.

### 4.1 데미지 계산 공식 체계

| 계산 항목 | 공식/방법 | 비고 |
|-----------|-----------|------|
| 기본 데미지 | 스킬 기본값 + (AD × AD계수) + (AP × AP계수) | Data Dragon에서 자동 로드 |
| 방어력 적용 | 데미지 × 100 / (100 + 유효 방어력) | 방어력 0 이상일 때 |
| 관통력 적용 순서 | 고정감소 → %감소 → %관통 → 치명력 | LoL Wiki 공식 기준 |
| 치명력(레탈리티) | 레탈리티 × (0.6 + 0.4 × 대상레벨/18) | 레벨 스케일링 |
| 크리티컬 | AD × (1.75 또는 아이템별 배율) | 인피니티 엣지 등 반영 |
| 흡혈/회복 | 데미지 × 흡혈% + 아이템 고정회복 | 중상 효과(40% 감소) 반영 |
| 방패 | 데미지 적용 전 방패량만큼 차감 | 뼈 방패, 불멸의 활 등 |
| 미니언 데미지 | 미니언 수 × 미니언 AD × (교전시간) | 방어력 적용 |

### 4.2 교전 시뮬레이션 시나리오

매 시점에서 4가지 시나리오를 계산하여 교전 여부를 판정합니다.

| 시나리오 | 설명 | 핵심 변수 |
|----------|------|-----------|
| 정면 교전 | 둘 다 제자리에서 풀콤보 교환 | 기본 1v1 결과 |
| 상대 후퇴 + 반격 | 상대가 빠지며 사거리 내 스킬만 사용 | 추격 시 DPS 차이 |
| 포탑 유인 | 상대가 포탑 밑으로 유인 → 다이브 여부 | 포탑 데미지 + 연속 증가 |
| 정글러 합류 | 상대 정글러가 합류하는 2v1 상황 | 도착 시간 기반 계산 |

### 4.3 교전 판정 결과

| 판정 | 조건 | 권고 | 등급 |
|------|------|------|------|
| 킬 가능 + 생존 | 모든 시나리오 유리 | 교전 강력 추천 | 🟢 GREEN |
| 킬 가능 + 위험 | 일부 시나리오 유리 | 조건부 교전 가능 | 🟡 YELLOW |
| 킬 불가 | 대부분 시나리오 불리 | 교전 비추천 | 🟠 ORANGE |
| 확정 사망 | 모든 시나리오 불리 | 절대 교전 금지 | 🔴 RED |

### 4.4 교전 시뮬레이션 코드 구조

```python
def simulate_full_fight(me, enemy, environment):
    """특정 시점에서 교전 시 결과를 시뮬레이션"""
    
    my_hp = me.hp
    enemy_hp = enemy.hp
    
    # 내 콤보 데미지 계산
    for skill in me.get_combo():
        raw_damage = calc_skill_damage(me, skill, enemy)
        after_resist = apply_resistance(raw_damage, enemy)
        after_shield = apply_shields(after_resist, enemy)  # 뼈 방패 등
        
        enemy_hp -= after_shield
        my_hp += calc_healing(me, after_shield)  # 흡혈/정복자 등
    
    # 상대 반격 데미지
    enemy_combo = calc_enemy_full_combo(enemy, me)
    my_hp -= enemy_combo
    
    # 미니언 데미지
    if environment.enemy_minions > 0:
        my_hp -= calc_minion_damage(environment, me)
    
    # 정글러 합류
    if environment.jungler_arrival_time < fight_duration:
        my_hp -= calc_jungler_damage(environment.enemy_jungler, me)
    
    # 위기 방패 (불멸의 활 등)
    if my_hp / me.max_hp <= 0.3:
        my_hp += calc_crisis_shields(me)
    
    return FightResult(
        my_hp_remaining=my_hp,
        enemy_hp_remaining=enemy_hp,
        can_kill=enemy_hp <= 0,
        i_survive=my_hp > 0,
        verdict=determine_verdict(my_hp, enemy_hp)
    )
```

### 4.5 시야 분석 엔진 (v2.0 업그레이드)

v1.0의 "보였다/안 보였다" 이진 판단에서 **시야 장악도(Vision Control Score)** 계산으로 업그레이드합니다.

#### 4.5.1 시야 장악도 계산

```python
class VisionControlResult:
    visible: bool                  # 기존: 단순 가시 여부
    vision_dominance: float        # NEW: 0.0~1.0 (1.0 = 완전 장악)
    vision_line_broken: bool       # NEW: 시야 라인 끊겼는가
    objective_vision_ready: bool   # NEW: 오브젝트 전 시야 준비됐는가
    danger_unwarded: list[str]     # NEW: 미와드 위험 구역 목록

def calc_vision_dominance(timestamp, my_team, enemy_team) -> VisionControlResult:
    """
    단순 가시 여부 → 시야 장악 점수 계산
    
    장악 지표:
    - 적 정글 시야 비율 (깊은 와드)
    - 강 주요 지점 시야 보유 여부
    - 오브젝트 주변 시야 반경 (드래곤/바론 기준 3000 이내)
    - 상대 와드 제거 수 (Control Ward 활용)
    """
    
    KEY_VISION_POINTS = {
        "dragon_pit": {"x": 9866, "y": 4414},
        "baron_pit":  {"x": 5007, "y": 10471},
        "river_mid":  {"x": 7500, "y": 7500},
        "blue_jungle_enemy": {"x": 3800, "y": 7900},  # 블루팀 기준
        "red_jungle_enemy":  {"x": 11200, "y": 7600},
    }
    
    controlled_points = 0
    for name, point in KEY_VISION_POINTS.items():
        if any_ward_covers(my_team.wards, point, radius=900):
            controlled_points += 1
    
    dominance = controlled_points / len(KEY_VISION_POINTS)
    
    # 오브젝트 전 시야 준비 여부 (오브젝트 스폰 60초 전 기준)
    next_obj = get_next_objective_spawn(timestamp)
    obj_vision = is_objective_vision_ready(my_team.wards, next_obj)
    
    return VisionControlResult(
        visible=basic_visibility_check(...),
        vision_dominance=dominance,
        vision_line_broken=dominance < 0.3,
        objective_vision_ready=obj_vision,
        danger_unwarded=find_unwarded_danger_zones(my_team, timestamp),
    )
```

#### 4.5.2 시야 관련 실수 분류 (확장)

| 실수 | 기존 | v2.0 추가 |
|------|------|-----------|
| 시야 없는 데스 | 죽기 전 상대 안 보임 | + "어느 와드가 있었으면 막을 수 있었는가" |
| 오브젝트 전 시야 실패 | ❌ 없음 | ✅ 오브젝트 60초 전 핵심 지점 미와드 |
| 시야 라인 밀림 | ❌ 없음 | ✅ 상대 와드가 아군 진영 깊이 박힌 상태 |
| 컨트롤 와드 미사용 | ❌ 없음 | ✅ 아이템에 있는데 경기 중 구매 0 |

### 4.6 감지하는 실수 유형 (v2.0 확장)

#### Combat 실수 (기존 유지)

| 실수 유형 | 감지 조건 | 엔진 |
|-----------|-----------|------|
| 오버 익스텐드 데스 | 타워에서 멀고, 아군 없고, 체력 낮은 상태에서 사망 | Combat |
| 시야 없는 데스 | 죽기 전 주변 시야 없음 + 상대가 안개에서 등장 | Combat + Vision |
| 보였는데 무시 | 상대 정글러가 시야에 보인 후 후퇴하지 않아 사망 | Combat + Vision |
| 불리한 교전 | 킬각 없는 상황(RED 판정)에서 교전 시도 | Combat |
| 킬 윈도우 놓침 | 킬각이 있었지만(GREEN) 교전하지 않음 | Combat |
| 스킬 낭비 | 스킬 사용 → 데미지 0 (빗나감) + 마나 부족으로 이어짐 | Combat |
| 궁 타이밍 실수 | 궁 사용 후 킬 없음 + 쿨다운 중 오브젝트 싸움 발생 | Combat |
| 소환사 주문 낭비 | 플래시/힐 사용 후 결국 사망 | Combat |

#### Wave 실수 ← NEW

| 실수 유형 | 감지 조건 | 엔진 |
|-----------|-----------|------|
| 불리 웨이브에서 교전 | 미니언 열세 상태에서 교전 시도 → Wave가 만든 불리 | Wave |
| 프리징 기회 놓침 | 킬 후 웨이브 관리 없이 귀환 → 미니언 손실 | Wave |
| 다이브 타이밍 미스 | 슬로우푸쉬 완성 전 조기 교전 | Wave |
| 무의미한 리셋 | 체력 충분한데 귀환 → 미니언 손실 + 템포 손해 | Wave |
| CS 놓침 패턴 | 라인에 혼자 있는데 분당 CS가 평균 이하 | Wave |

#### Tempo 실수 ← NEW

| 실수 유형 | 감지 조건 | 엔진 |
|-----------|-----------|------|
| 늦은 리콜 | 골드 쌓여 있는데 라인에 남아 추가 위험 감수 | Tempo |
| 이른 리콜 | 파워 스파이크 직전 귀환 → 상대에게 템포 헌납 | Tempo |
| 아이템 타이밍 격차 | 상대 핵심 아이템 완성 후 무리한 교전 | Tempo |
| 오브젝트 전 리콜 | 드래곤/바론 스폰 90초 내 귀환 | Tempo |

#### Macro 실수 ← NEW

| 실수 유형 | 감지 조건 | 엔진 |
|-----------|-----------|------|
| 사이드 기회 놓침 | 한타 합류 대신 사이드 밀었어야 하는 상황 | Macro |
| 잘못된 오브젝트 선택 | 드래곤 < 바론인 상황에서 드래곤 | Macro |
| 와드 관리 부족 | 오브젝트 60초 전 핵심 지점 미와드 | Vision |
| 오브젝트 후 산개 | 오브젝트 획득 후 사이드로 이점 전환 없이 산개 | Macro |

### 4.7 킬 윈도우 탐색기

경기 전체에서 킬 가능했던 시점을 모두 찾아냅니다.

```python
def find_all_kill_windows(match_data, analysis_interval=5):
    """경기 전체에서 킬 가능했던 시점을 모두 찾음"""
    kill_windows = []
    
    for timestamp in range(0, match_data.duration, analysis_interval):
        me = match_data.get_player_state(timestamp, "me")
        enemy = match_data.get_player_state(timestamp, "opponent")
        env = match_data.get_environment(timestamp)
        
        scenarios = analyze_fight_scenarios(me, enemy, env)
        
        if scenarios.verdict in ["GREEN", "YELLOW"]:
            kill_windows.append({
                "time": timestamp,
                "verdict": scenarios.verdict,
                "conditions": extract_favorable_conditions(me, enemy, env),
                "scenarios": scenarios
            })
    
    return kill_windows
```

---

---

## 5. Wave Analysis Engine ⭐ NEW

> **GPT 피드백 핵심 #1**: "킬각 판단은 웨이브에 강하게 의존함. 미니언 많으면 → 싸우면 손해, 프리징 → 갱 위험, 푸쉬 → 다이브 가능"

### 5.1 Wave State 정의

웨이브 상태는 모든 교전/리콜/로테이션 판단의 **전제 조건**입니다.

| 웨이브 상태 | 정의 | 전략적 의미 |
|-------------|------|-------------|
| `FAST_PUSH` | 아군 미니언 수 >> 적 미니언 수 | 빠르게 타워에 붙이고 귀환/로밍 가능 |
| `SLOW_PUSH` | 아군이 조금씩 우세, 큰 웨이브 만드는 중 | 다이브 유도 / 오브젝트 연계 준비 |
| `FREEZE` | 적 타워 근처에서 미니언 수 균형 유지 | 상대 CS 굶기기, 갱 유도 |
| `EVEN` | 미니언 수 균형 | 중립 상태 |
| `CRASHING` | 큰 웨이브가 타워로 충돌 직전 | 귀환 타이밍 / 로밍 타이밍 |
| `LOSING_WAVE` | 적 미니언이 아군 타워 방향으로 밀리는 중 | 교전 시 미니언 어그로 위험 ↑ |

### 5.2 Wave State 감지 알고리즘

```python
@dataclass
class WaveState:
    state: str                    # FAST_PUSH / SLOW_PUSH / FREEZE / EVEN / CRASHING / LOSING_WAVE
    my_minion_count: int
    enemy_minion_count: int
    minion_advantage: float       # +값 = 아군 우세, -값 = 적 우세
    wave_position: float          # 0.0 = 아군 타워, 1.0 = 적 타워
    next_crash_estimate_sec: float  # 예상 웨이브 충돌까지 남은 초
    cs_loss_if_recalled_now: int  # 지금 귀환 시 손실 CS
    fight_risk_modifier: float    # 교전 위험 계수 (1.0 기준, >1.0 = 더 위험)

def detect_wave_state(timestamp_ms: int, snapshots: dict, player_id: int) -> WaveState:
    """
    미니언 수 + 위치 데이터로 웨이브 상태 판단
    """
    snap = get_snapshot_at(timestamp_ms, snapshots)
    my_minions = [m for m in snap["minions"] if m["team"] == get_player_team(snap, player_id)]
    enemy_minions = [m for m in snap["minions"] if m["team"] != get_player_team(snap, player_id)]
    
    my_count = len(my_minions)
    enemy_count = len(enemy_minions)
    advantage = my_count - enemy_count
    
    # 웨이브 위치 (미니언 평균 X 좌표로 근사)
    wave_x = mean([m["position"]["x"] for m in my_minions + enemy_minions])
    wave_position = normalize_position(wave_x, player_team)
    
    # 상태 분류
    if advantage >= 4 and wave_position > 0.6:
        state = "FAST_PUSH"
        fight_risk = 0.8   # 교전 후 귀환 가능 → 위험 낮음
    elif advantage >= 2:
        state = "SLOW_PUSH"
        fight_risk = 0.9
    elif advantage <= -3 and wave_position < 0.4:
        state = "FREEZE"
        fight_risk = 1.5   # 적 진영에서 얼어있는 웨이브 → 교전 매우 위험
    elif wave_position > 0.85:
        state = "CRASHING"
        fight_risk = 0.7   # 크래쉬 직전 → 귀환/로밍 타이밍
    elif advantage <= -2:
        state = "LOSING_WAVE"
        fight_risk = 1.4   # 적 미니언 많음 → 어그로 위험
    else:
        state = "EVEN"
        fight_risk = 1.0
    
    # 귀환 시 CS 손실 계산
    cs_loss = estimate_cs_loss_on_recall(my_minions, enemy_minions)
    
    return WaveState(
        state=state,
        my_minion_count=my_count,
        enemy_minion_count=enemy_count,
        minion_advantage=advantage,
        wave_position=wave_position,
        next_crash_estimate_sec=estimate_crash_time(my_minions, enemy_minions),
        cs_loss_if_recalled_now=cs_loss,
        fight_risk_modifier=fight_risk,
    )
```

### 5.3 Wave × Combat 통합

웨이브 상태가 교전 시뮬레이션의 **입력값**이 됩니다.

```python
def simulate_full_fight(me, enemy, env, wave_state: WaveState):
    # 기존 교전 시뮬레이션
    base_result = _run_combat_sim(me, enemy, env)
    
    # Wave 보정
    # 1. 미니언 어그로 데미지 (wave_state 기반으로 정확한 수 계산)
    actual_minion_damage = calc_minion_damage(
        enemy_minion_count=wave_state.enemy_minion_count,  # ← 기존: env.enemy_minion_count (근사값)
        fight_duration=base_result.fight_duration,
        defender=me,
    )
    
    # 2. 교전 위험 계수 반영 (FREEZE 상태에서 교전 → 더 위험)
    adjusted_my_hp = base_result.my_hp_remaining - actual_minion_damage
    adjusted_my_hp *= (2.0 - wave_state.fight_risk_modifier)  # 위험할수록 생존 가능성 낮춤
    
    # 3. 판정에 wave_state 이유 추가
    reason = _build_reason(base_result, wave_state)
    
    return FightResult(
        ...,
        wave_context=wave_state,      # ← NEW: 교전이 왜 불리한지 wave 이유 포함
        reason=reason,
    )

# 예시 이유 생성:
# "RED — 체력 불리 + 적 미니언 6마리 어그로 (LOSING_WAVE 상태)"
# vs 기존: "RED — 체력 불리"
```

### 5.4 Wave 분석으로 답할 수 있는 질문

| 질문 | v1.0 | v2.0 |
|------|------|------|
| "왜 싸우면 안 됐나요?" | "체력이 부족했습니다" | "체력 + **적 미니언 6마리 어그로로 추가 240 데미지** (LOSING_WAVE 상태)" |
| "왜 여기서 귀환했나요?" | ❌ 분석 불가 | "**웨이브가 CRASHING 상태**, 귀환하면 CS 손실 2개로 최적 타이밍" |
| "왜 킬각이 생겼나요?" | "체력/쿨다운 유리" | "체력 + **웨이브 SLOW_PUSH 완성** → 다이브 후 귀환 가능" |

### 5.5 Wave 분석 — Layer 1~2 반영

Layer 2 이벤트에 wave 컨텍스트 추가:

```json
{
  "time": "4:12",
  "type": "solo_death",
  "fight_verdict": "RED — 적 미니언 어그로 포함 시 생존 불가",
  "wave_context": {
    "state": "LOSING_WAVE",
    "my_minions": 2,
    "enemy_minions": 7,
    "fight_risk_modifier": 1.4,
    "note": "웨이브 열세 상태에서 교전 — 미니언 어그로로 추가 280 데미지"
  }
}
```

---

## 6. Tempo & Recall Engine ⭐ NEW

> **GPT 피드백 핵심 #2**: "리콜 타이밍 → 오브젝트 영향 / 아이템 타이밍 기반 파워 스파이크"

### 6.1 리콜 타이밍 평가 시스템

리콜 이벤트를 감지하고 "이 리콜이 최적 타이밍이었는가"를 평가합니다.

```python
@dataclass
class RecallEvaluation:
    timestamp_ms: int
    grade: str              # OPTIMAL / GOOD / WASTEFUL / DANGEROUS
    gold_at_recall: int
    cs_loss: int            # 귀환 중 손실한 CS
    item_bought: list[int]  # 귀환 후 구매한 아이템
    power_spike_gained: bool    # 핵심 아이템 완성 여부
    objective_missed: bool      # 귀환 중 오브젝트 발생 여부
    time_away_sec: float       # 라인 부재 시간
    reasoning: str

def evaluate_recall(
    recall_ts: int,
    gold: int,
    wave_state: WaveState,
    next_objective_ts: int,
    snapshots: dict,
    item_thresholds: dict,  # {champion_id: {item_id: cost, ...}}
) -> RecallEvaluation:
    """
    리콜 타이밍 평가
    
    OPTIMAL 조건:
      1. 웨이브 CRASHING 또는 FAST_PUSH (CS 손실 최소)
      2. 핵심 아이템 구매 가능한 골드 보유
      3. 오브젝트 스폰 120초 이상 여유
    
    DANGEROUS 조건:
      1. 오브젝트 스폰 90초 이내
      2. 웨이브 LOSING_WAVE (라인 손해)
      3. 팀이 교전 중인 상황
    """
    cs_loss = wave_state.cs_loss_if_recalled_now
    time_to_objective = (next_objective_ts - recall_ts) / 1000
    
    # 아이템 파워 스파이크 체크
    target_items = item_thresholds.get(player_champion_id, {})
    power_spike = any(gold >= cost for cost in target_items.values())
    
    if wave_state.state in ("CRASHING", "FAST_PUSH") and power_spike and time_to_objective > 120:
        grade = "OPTIMAL"
    elif cs_loss <= 2 and time_to_objective > 90:
        grade = "GOOD"
    elif time_to_objective < 90:
        grade = "DANGEROUS"
        reasoning = f"오브젝트 {time_to_objective:.0f}초 후 스폰 — 귀환하면 불참 가능"
    elif cs_loss >= 6:
        grade = "WASTEFUL"
        reasoning = f"귀환 중 CS {cs_loss}개 손실 예상"
    else:
        grade = "GOOD"
    
    return RecallEvaluation(...)
```

### 6.2 아이템 파워 스파이크 시스템

챔피언별 핵심 아이템 완성 시점을 기준으로 **템포 격차**를 분석합니다.

```python
# 챔피언별 파워 스파이크 아이템 (Data Dragon + 커뮤니티 데이터)
POWER_SPIKE_THRESHOLDS = {
    "Yasuo": {
        "first_item": {"Trinity Force": 3333, "Immortal Shieldbow": 3400},
        "second_item": {"Infinity Edge": 3400},
        "level_spike": [6, 9, 11],   # 6레벨(궁), 9레벨(Q3풀업), 11레벨(궁 렙업)
    },
    "Ahri": {
        "first_item": {"Luden's Tempest": 3200, "Shadowflame": 3000},
        "second_item": {"Rabadon's Deathcap": 3600},
        "level_spike": [6, 11, 16],
    },
    # ...
}

def calc_power_spike_tempo(
    player_gold_history: dict,   # {timestamp_ms: gold}
    enemy_gold_history: dict,
    player_champion: str,
    enemy_champion: str,
) -> list[dict]:
    """
    두 챔피언의 파워 스파이크 타이밍 비교
    
    Returns: [{
        "timestamp_ms": ...,
        "event": "PLAYER_SPIKE" | "ENEMY_SPIKE" | "BOTH",
        "player_item": "Trinity Force",
        "enemy_item": None,
        "tempo_advantage": "PLAYER" | "ENEMY" | "EVEN",
        "fight_recommendation": "ENGAGE" | "AVOID" | "NEUTRAL"
    }]
    """
    spikes = []
    player_thresholds = POWER_SPIKE_THRESHOLDS.get(player_champion, {})
    enemy_thresholds = POWER_SPIKE_THRESHOLDS.get(enemy_champion, {})
    
    for ts, gold in sorted(player_gold_history.items()):
        enemy_gold = enemy_gold_history.get(ts, 0)
        
        player_items_completed = [
            item for item, cost in player_thresholds.get("first_item", {}).items()
            if gold >= cost
        ]
        enemy_items_completed = [
            item for item, cost in enemy_thresholds.get("first_item", {}).items()
            if enemy_gold >= cost
        ]
        
        if player_items_completed and not enemy_items_completed:
            spikes.append({
                "timestamp_ms": ts,
                "tempo_advantage": "PLAYER",
                "fight_recommendation": "ENGAGE",  # 파워 스파이크 우위 → 교전 권장
            })
    
    return spikes
```

### 6.3 Tempo 분석이 가능하게 하는 코칭

| 기존 코칭 | v2.0 Tempo 코칭 |
|-----------|-----------------|
| "4:12에 왜 죽었나요?" — 체력 부족 | "4:12에 왜 죽었나요?" — **삼위일체 완성 전(골드 1200 부족)** 아리가 첫 템 완성 후 라인 강세 구간에 교전 |
| (분석 없음) | "7:30이 킬각이었던 이유: **삼위일체 완성 + 아리 쿨다운 + CRASHING 웨이브**" |
| (분석 없음) | "12:20 리콜은 WASTEFUL — CS 8개 손실, 바론 전 90초 이내 귀환" |

### 6.4 Tempo 관련 Layer 2 이벤트 추가

```json
{
  "time": "12:20",
  "type": "recall",
  "title": "리콜 타이밍 평가",
  "grade": "WASTEFUL",
  "severity": "important",
  "detail": {
    "gold_at_recall": 2800,
    "cs_loss_estimated": 8,
    "item_spike_available": false,
    "time_to_baron": 85,
    "reasoning": "바론 85초 전 귀환 — 참여 실패 위험, 핵심 아이템도 미완성"
  }
}
```

---

## 7. Macro Decision Engine ⭐ NEW

> **GPT 피드백 핵심 #3**: "싸움 vs 사이드 vs 오브젝트 최적 선택 추천 / 오브젝트 선택 판단 로직"

### 7.1 매크로 판단 프레임워크

모든 주요 이벤트(킬, 오브젝트, 타워 파괴) 직후 **최적 행동**과 **실제 행동**을 비교합니다.

```python
@dataclass
class MacroDecision:
    timestamp_ms: int
    trigger: str           # "KILL" | "OBJECTIVE_SPAWN" | "TOWER_DESTROY" | "TEAMFIGHT_WIN"
    
    # 가능한 선택지
    options: list[MacroOption]
    
    # 최적 선택
    optimal: MacroOption
    
    # 실제 선택
    actual: MacroOption
    
    # 판정
    correct: bool
    missed_value: str      # 잘못된 선택으로 잃은 것 (골드 가치)

@dataclass
class MacroOption:
    action: str            # "FIGHT" | "SIDE_LANE" | "DRAGON" | "BARON" | "TOWER" | "RESET"
    estimated_gold_value: int
    estimated_map_pressure: float  # 0.0~1.0
    risk: float            # 0.0~1.0
    score: float           # 종합 점수
```

### 7.2 오브젝트 선택 로직

"드래곤이냐 바론이냐"를 수치로 판단합니다.

```python
def evaluate_objective_choice(
    timestamp_ms: int,
    game_state: dict,
    available_objectives: list[str],
) -> dict:
    """
    오브젝트 우선순위 계산
    
    고려 요소:
    - 오브젝트 골드/스택 가치
    - 현재 팀 상태 (체력, 스킬 쿨다운)
    - 시야 준비 여부
    - 사이드 압박 상황
    - 상대 스폰 타이머
    """
    OBJECTIVE_BASE_VALUES = {
        "dragon_1st": 800,    # 드래곤 소울 스택 1
        "dragon_soul": 3000,  # 드래곤 소울 (4스택)
        "baron": 1500,        # 팀 골드 가치 (미니언 버프)
        "elder_dragon": 4000, # 장로 드래곤
        "rift_herald": 600,   # 균열 전령 (타워 압박)
        "turret": 850,        # 외부 타워 첫 번째
    }
    
    scores = {}
    for obj in available_objectives:
        base_value = OBJECTIVE_BASE_VALUES.get(obj, 0)
        
        # 팀 상태 보정
        avg_hp_pct = calc_team_avg_hp(game_state)
        hp_modifier = 0.7 if avg_hp_pct < 0.5 else 1.0  # 체력 낮으면 가치 하락
        
        # 시야 준비 보정
        vision_ready = check_objective_vision(game_state, obj)
        vision_modifier = 0.8 if not vision_ready else 1.0
        
        # 상대 스폰 타이머 보정
        enemy_respawn_sec = calc_enemy_respawn(game_state)
        urgency = min(1.5, 30 / max(1, enemy_respawn_sec))  # 30초 이내면 빠르게 먹어야
        
        scores[obj] = base_value * hp_modifier * vision_modifier * urgency
    
    best = max(scores, key=scores.get)
    return {
        "recommended": best,
        "scores": scores,
        "reasoning": build_macro_reason(best, scores, game_state),
    }
```

### 7.3 사이드 vs 한타 판단

```python
def evaluate_side_vs_teamfight(
    timestamp_ms: int,
    game_state: dict,
    player_champion: str,
    team_composition: list[str],
) -> dict:
    """
    사이드 밀기 vs 한타 합류 중 최적 판단
    
    사이드가 유리한 조건:
    - 1v1 가능한 챔피언 (야스오, 피오라, 제이스)
    - 사이드 타워 압박으로 상대 팀 분산 가능
    - 팀 한타력이 낮을 때
    
    한타가 유리한 조건:
    - 한타 챔피언 (말파이트, 아무무)
    - 오브젝트 근처
    - 팀 상태 양호
    """
    SIDE_PREFERRED_CHAMPS = {
        "Fiora", "Camille", "Jax", "Tryndamere", "Yasuo", "Gangplank"
    }
    TEAMFIGHT_PREFERRED_CHAMPS = {
        "Malphite", "Amumu", "Orianna", "Sona", "Sejuani"
    }
    
    is_split_pusher = player_champion in SIDE_PREFERRED_CHAMPS
    has_tp = check_spell_available(game_state, "Teleport")
    side_tower_pressure = calc_side_tower_hp(game_state, player_champion)
    
    if is_split_pusher and has_tp and side_tower_pressure < 0.5:
        return {
            "recommendation": "SIDE_LANE",
            "reason": f"{player_champion}은 사이드 압박 후 텔포 합류가 최적",
            "tp_target": "teamfight",
        }
    
    # 팀 한타력 점수
    team_fight_score = sum(
        1 for champ in team_composition
        if champ in TEAMFIGHT_PREFERRED_CHAMPS
    )
    
    if team_fight_score >= 3:
        return {
            "recommendation": "TEAMFIGHT",
            "reason": "팀 한타 구성 강력 — 합류 권장",
        }
    
    return {"recommendation": "NEUTRAL", "reason": "양방향 모두 유효"}
```

### 7.4 Macro Decision이 Layer 2에 추가되는 방식

```json
{
  "time": "18:30",
  "type": "macro_decision",
  "trigger": "TEAMFIGHT_WIN (3킬)",
  "title": "교전 승리 후 매크로 판단",
  "severity": "important",
  "optimal_action": {
    "action": "BARON",
    "reasoning": "상대 스폰 38초, 시야 준비됨, 팀 체력 70%+ — 바론 즉시 시도"
  },
  "actual_action": {
    "action": "RESET",
    "reasoning": "전원 귀환"
  },
  "correct": false,
  "missed_value": "바론 골드 가치 ~1500골드 + 미니언 버프 압박 손실",
  "benchmark": "챌린저 87% 이 상황에서 바론 시도"
}
```

### 7.5 Macro Decision이 답할 수 있는 질문

| 질문 | 기존 | v2.0 |
|------|------|------|
| "18:30 교전 이기고 왜 졌어요?" | ❌ 분석 불가 | "**바론 안 먹고 귀환** — 스폰 38초 남은 상대 기다려줌. 챌린저 87% 바론 시도" |
| "20:00에 왜 드래곤 안 먹었어요?" | ❌ 분석 불가 | "**바론이 우선순위** (스코어: 바론 2100 > 드래곤 800) — 시야 없이 드래곤은 낭비" |
| "야스오인데 한타 가야 했나요?" | ❌ 분석 불가 | "**사이드 압박 + 텔포**가 최적 — 바텀 타워 HP 30%, 텔포 쿨다운 사용 가능" |

---

## 8. Predictive Simulation Engine ⭐ NEW (v3.0)

> **GPT 피드백**: "10~20초 뒤 상황 시뮬레이션, '이대로 가면 갱 당함' 경고, '이 타이밍에 싸우면 손해' 사전 판단"

현재 교전 결과 판단(사후 분석)에서 **미래 예측**(사전 경고)으로 분석의 차원을 확장합니다.

### 8.1 예측 시뮬레이션 개요

```python
@dataclass
class PredictiveResult:
    lookahead_sec: int          # 예측 범위 (10 또는 20초)
    predicted_event: str        # "GANK_RISK" | "FIGHT_LOSS" | "KILL_OPPORTUNITY" | "SAFE"
    confidence: float           # 0.0~1.0
    trigger_reason: str         # 예측의 근거
    recommended_action: str     # 권고 행동
    ev_score: float             # 기대값 점수 (양수 = 유리)

class PredictiveSimulationEngine:
    """
    현재 게임 상태에서 10~20초 후 발생 가능한 상황을 예측
    
    핵심 시나리오:
    1. 갱 위험 예측 — 정글러 이동 경로 추적
    2. 교전 결과 예측 — EV(기대값) 모델
    3. 오브젝트 선점 창 예측 — 스폰 타이머 × 팀 상태
    """
    
    LOOKAHEAD_MS = 15_000   # 15초 예측
    GANK_SPEED_PX_SEC = 380  # 정글러 평균 이동 속도
    
    async def predict(self, timestamp_ms: int, snapshots: dict, player_id: int) -> PredictiveResult:
        snap = snapshots[timestamp_ms]
        
        # 1. 갱 위험 예측
        gank_risk = self._predict_gank_risk(timestamp_ms, snapshots, snap, player_id)
        if gank_risk.confidence > 0.7:
            return gank_risk
        
        # 2. 킬 창 예측 (10~20초 안에 상대 체력/쿨다운 조건이 맞는가)
        kill_window = self._predict_kill_window(timestamp_ms, snapshots, snap, player_id)
        if kill_window.ev_score > 0.5:
            return kill_window
        
        # 3. 오브젝트 창 예측
        obj_window = self._predict_objective_window(timestamp_ms, snap)
        return obj_window
    
    def _predict_gank_risk(self, ts_ms, snapshots, snap, player_id) -> PredictiveResult:
        """
        정글러의 마지막 목격 위치 + 이동 속도로 도달 가능 구역 계산
        
        갱 위험 조건:
        1. 상대 정글러 MIA (마지막 시야 > 30초 전)
        2. 정글러 마지막 위치에서 15초 내 플레이어 위치 도달 가능
        3. 플레이어가 타워에서 멀고 와드가 없는 상황
        """
        enemy_jungler = self._get_enemy_jungler(snap)
        last_seen_ts = self._last_seen_timestamp(enemy_jungler["id"], snapshots, ts_ms)
        mia_sec = (ts_ms - last_seen_ts) / 1000
        
        if mia_sec < 15:
            return PredictiveResult(predicted_event="SAFE", confidence=0.2, ev_score=0.0,
                                    trigger_reason="정글러 시야 확보됨", recommended_action="계속")
        
        # 15초 내 도달 가능한 거리
        max_travel_px = self.GANK_SPEED_PX_SEC * self.LOOKAHEAD_MS / 1000
        last_pos = enemy_jungler.get("last_seen_position", {"x": 0, "y": 0})
        player_pos = self._get_player_position(snap, player_id)
        dist = euclidean_distance(last_pos, player_pos)
        
        if dist < max_travel_px:
            # 갱 경로 상에 와드가 없는지 확인
            gank_path = self._compute_gank_path(last_pos, player_pos)
            warded = any_ward_covers_path(snap["wards"], gank_path)
            
            confidence = min(0.95, (1 - dist / max_travel_px) * (0.5 if warded else 1.0))
            return PredictiveResult(
                lookahead_sec=15,
                predicted_event="GANK_RISK",
                confidence=confidence,
                trigger_reason=f"정글러 MIA {mia_sec:.0f}초, 도달 가능 거리 {dist:.0f}px, 시야 없음",
                recommended_action="즉시 타워 방향으로 후퇴 또는 와드 설치 후 유지",
                ev_score=-confidence,
            )
        
        return PredictiveResult(predicted_event="SAFE", confidence=0.6, ev_score=0.1,
                                trigger_reason=f"정글러 위치 {dist:.0f}px — 도달 불가", recommended_action="계속")
```

### 8.2 EV(기대값) 모델 — 위험/보상 분석

```python
def calc_expected_value(
    fight_result: FightResult,
    context: dict,
) -> float:
    """
    교전의 기대값 계산 (EV > 0 = 유리한 교전)
    
    EV = (킬 확률 × 보상) - (데스 확률 × 손실)
    """
    # 보상
    kill_gold = 300 + context.get("bounty_gold", 0)
    objective_gold = context.get("next_objective_value", 0)  # 킬 후 오브젝트 가능하면 추가
    
    # 손실  
    death_gold = 300 + context.get("my_bounty", 0)  # 내 현상금
    cs_loss_on_death = context.get("cs_loss_from_death", 0) * 21  # CS당 21골드
    tempo_loss = context.get("tempo_loss_gold", 0)  # 귀환/재등장 중 손실 골드
    
    # 확률 (FightResult에서 추출)
    p_kill = 1.0 if fight_result.can_kill else 0.3 * max(0, fight_result.enemy_hp_remaining)
    p_death = 1.0 if fight_result.my_hp_remaining <= 0 else max(0, -fight_result.my_hp_remaining / 100)
    
    ev = (p_kill * (kill_gold + objective_gold)) - (p_death * (death_gold + cs_loss_on_death + tempo_loss))
    
    # 웨이브 보정
    wave_bonus = context.get("wave_crash_value", 0)  # 교전 후 웨이브 크래쉬 가능하면 +
    
    return ev + wave_bonus
```

### 8.3 Predictive Engine이 가능하게 하는 코칭

| 기존 코칭 | v3.0 Predictive 코칭 |
|-----------|----------------------|
| "4:12에 갱 당해서 죽었습니다" (사후 분석) | "4:00에 **15초 내 갱 위험 감지** — MIA 45초, 타워에서 900px. 4:00에 후퇴했으면 회피 가능" |
| "킬각을 놓쳤습니다" | "3:50~4:05 사이 **EV +420골드 교전 창** — 상대 쿨다운 + 체력 열세 (이 창을 놓침)" |
| (분석 없음) | "6:00 드래곤 전 **40초 내 킬 창** — 지금 교전하면 킬 후 드래곤 연계 EV +1,200골드" |

---

## 9. Game State Engine ⭐ NEW (v3.0)

> **GPT 피드백**: "현재 게임이 이기고 있는지 지고 있는지 모르는 유저 많음. 국면 인식 + 그에 맞는 플레이 제안"

### 9.1 게임 국면 분류

```python
@dataclass
class GameState:
    timestamp_ms: int
    phase: str              # "AHEAD" | "EVEN" | "BEHIND" | "SNOWBALL" | "COMEBACK"
    gold_lead: int          # 팀 골드 리드 (+ = 아군 우세)
    tower_lead: int         # 타워 수 차이
    dragon_stack: int       # 내 팀 드래곤 스택
    baron_active: bool      # 현재 바론 버프 보유 여부
    kill_lead: int          # 킬 수 차이
    
    # 스케일링 판단
    team_scaling: str       # "EARLY" | "MID" | "LATE" | "ALL_GAME"
    enemy_scaling: str
    tempo_advantage: str    # "AHEAD" | "EVEN" | "BEHIND"
    
    # 권고 행동 기조
    macro_stance: str       # "PRESS" | "STABILIZE" | "SURVIVE" | "FARM_SCALE"
    reasoning: str

class GameStateEngine:
    GOLD_LEAD_AHEAD = 3000
    GOLD_LEAD_SNOWBALL = 8000
    
    def classify(self, timestamp_ms: int, match_data: dict) -> GameState:
        """
        실시간 게임 국면 분류
        
        AHEAD:     골드/타워/킬 모두 우세 → 계속 압박
        EVEN:      팽팽한 상황 → 실수 없이 안정적으로
        BEHIND:    골드/타워 열세 → 사이드 파밍 / 스케일 대기
        SNOWBALL:  8,000+ 골드 리드 → 공격적 엔딩 시도
        COMEBACK:  뒤처진 상태에서 스케일링 챔피언 → 팜 집중
        """
        gold_lead = self._calc_gold_lead(match_data, timestamp_ms)
        tower_lead = self._calc_tower_lead(match_data, timestamp_ms)
        kill_lead = self._calc_kill_lead(match_data, timestamp_ms)
        
        if gold_lead > self.GOLD_LEAD_SNOWBALL:
            phase = "SNOWBALL"
            stance = "PRESS"
            reason = f"골드 리드 {gold_lead:,} — 스노우볼 단계, 공격적 엔딩 시도"
        elif gold_lead > self.GOLD_LEAD_AHEAD:
            phase = "AHEAD"
            stance = "PRESS"
            reason = f"골드 리드 {gold_lead:,}, 타워 {tower_lead}개 우세"
        elif abs(gold_lead) < 1500 and abs(tower_lead) <= 1:
            phase = "EVEN"
            stance = "STABILIZE"
            reason = "팽팽한 국면 — 실수를 줄이는 것이 핵심"
        else:
            # 뒤처진 상황 — 스케일링 체크
            team_scaling = self._get_scaling_type(match_data["my_team"])
            phase = "BEHIND"
            if team_scaling == "LATE":
                stance = "FARM_SCALE"
                reason = f"골드 열세 {abs(gold_lead):,} + 후반 스케일링 조합 → 팜 집중, 싸움 최소화"
            else:
                stance = "SURVIVE"
                reason = f"골드 열세 {abs(gold_lead):,} + 초/중반 조합 → 픽 찬스만 노리기"
        
        return GameState(phase=phase, macro_stance=stance, reasoning=reason, ...)
```

### 9.2 스노우볼 곡선 추적

경기 전체의 골드 리드 추이를 타임라인으로 시각화합니다.

```json
// Layer 1에 추가되는 game_state_timeline
{
  "game_state_timeline": [
    { "time": "5:00", "phase": "EVEN", "gold_lead": 200 },
    { "time": "10:00", "phase": "BEHIND", "gold_lead": -1500,
      "trigger": "데스 3회 연속 — 골드 역전" },
    { "time": "15:00", "phase": "BEHIND", "gold_lead": -3200,
      "trigger": "드래곤 2스택 내줌" },
    { "time": "20:00", "phase": "BEHIND", "gold_lead": -5000,
      "macro_stance": "FARM_SCALE",
      "note": "후반 조합 — 30분 이후 스케일 타이밍 대기" }
  ],
  "turning_point": "10:00 — 3연속 데스로 골드 역전. 이후 회복 실패"
}
```

### 9.3 국면별 코칭 메시지

| 국면 | 잘못한 경우 | v3.0 코칭 |
|------|------------|-----------|
| SNOWBALL | 갱킹 대신 사이드 파밍 | "골드 리드 9,000 스노우볼 단계 — 팀이 함께 타워 밀고 엔딩 시도가 최적. 사이드 파밍은 이점 낭비" |
| BEHIND | 무리한 교전 계속 | "5,000 골드 열세 + 후반 조합 — 이 단계에서 교전은 더 뒤처짐. 팜 유지하며 35분 스케일 타이밍 대기" |
| EVEN | 오브젝트 포기 | "팽팽한 국면에서 드래곤을 내줌 — 미세한 우위가 쌓여 패배로 이어짐" |

---

## 10. Draft & Composition Analyzer ⭐ NEW (v3.0)

> **GPT 피드백**: "챔피언 조합의 강약점 이해 없이는 '왜 그 상황에서 그 플레이가 맞는가'를 설명 불가"

### 10.1 팀 조합 분류 시스템

```python
COMP_ARCHETYPES = {
    "POKE": {
        "description": "장거리 견제 중심 — 전투 전 체력 깎기",
        "win_condition": "적을 50% 이하로 만든 뒤 오브젝트 진입",
        "play_style": "직접 교전 최소화, 강 지점 장거리 유지",
        "countered_by": ["ENGAGE", "DIVE"],
        "key_champs": ["Jayce", "Ezreal", "Zoe", "Lux", "Karma"],
    },
    "ENGAGE": {
        "description": "강제 교전 진영 — CC로 한타 시작",
        "win_condition": "주요 CC기 적중 → 순간적 수적 우세 창출",
        "play_style": "시야 장악 후 팀 교전 강요",
        "countered_by": ["POKE", "KITE"],
        "key_champs": ["Malphite", "Amumu", "Leona", "Nautilus"],
    },
    "SPLIT_PUSH": {
        "description": "스플릿 압박 — 사이드에서 1v1 주도권",
        "win_condition": "텔포 연계로 사이드 압박 + 한타 참여",
        "play_style": "사이드 우선, 팀은 카운터 전략 필요",
        "countered_by": ["ENGAGE (5인 합류)"],
        "key_champs": ["Fiora", "Camille", "Jax", "Tryndamere"],
    },
    "TEAMFIGHT": {
        "description": "5인 한타 조합",
        "win_condition": "5v5 교전에서 AoE 스킬 극대화",
        "play_style": "오브젝트 중심, 시야 우선",
        "key_champs": ["Orianna", "Sejuani", "Miss Fortune"],
    },
    "SCALING": {
        "description": "후반 스케일링 조합 — 초중반 생존이 핵심",
        "win_condition": "아이템 2~3개 완성 후 교전 강세",
        "play_style": "교전 최소화, CS 극대화, 오브젝트 교환",
        "key_champs": ["Kassadin", "Veigar", "Jinx", "Kayle"],
    },
}

class CompositionAnalyzer:
    def analyze(self, my_team: list[str], enemy_team: list[str]) -> CompositionReport:
        my_comp = self._classify_team(my_team)
        enemy_comp = self._classify_team(enemy_team)
        
        matchup = self._evaluate_matchup(my_comp, enemy_comp)
        
        return CompositionReport(
            my_archetype=my_comp.archetype,
            enemy_archetype=enemy_comp.archetype,
            win_condition=my_comp.win_condition,
            phase_advantage=self._calc_phase_advantage(my_comp, enemy_comp),
            # {"early": "ENEMY", "mid": "EVEN", "late": "PLAYER"}
            key_threats=self._identify_threats(enemy_team, my_team),
            recommended_playstyle=matchup.my_recommendation,
        )
```

### 10.2 매치업 이해 — 개인 라인 분석

```python
MATCHUP_DATA = {
    ("Yasuo", "Ahri"): {
        "phase": {
            "early": {"advantage": "ENEMY", "reason": "아리 E(매혹) 적중 시 풀콤보 — 레벨 1~5 매우 불리"},
            "mid": {"advantage": "PLAYER", "reason": "야스오 1템 완성 후 바람장벽으로 Q 회피 가능"},
            "late": {"advantage": "PLAYER", "reason": "야스오 크리 스케일링 > 아리 단일 타겟"},
        },
        "key_tip": "아리 E 쿨다운(14초) 확인 후 교전 시작. W 이후 즉시 Q 연계",
        "danger_zone": "레벨 6 아리 궁 — 2연속 돌진으로 확정 킬각",
    },
}

def get_matchup_context(player_champ: str, enemy_champ: str, game_time_min: int) -> dict:
    data = MATCHUP_DATA.get((player_champ, enemy_champ), {})
    phase = "early" if game_time_min < 10 else "mid" if game_time_min < 20 else "late"
    return {
        "current_phase_advantage": data.get("phase", {}).get(phase, {}),
        "key_tip": data.get("key_tip", ""),
        "danger": data.get("danger_zone", ""),
    }
```

### 10.3 Composition Analyzer가 가능하게 하는 코칭

| 질문 | 기존 | v3.0 |
|------|------|------|
| "왜 한타에 안 갔나요?" | ❌ | "야스오 **SPLIT_PUSH 조합** — 사이드 압박 + 텔포가 최적. 팀 한타력 낮아 합류 비효율" |
| "왜 계속 지나요?" | ❌ | "**아리가 레벨 1~5 구간 강세** — 이 구간 아리 E 쿨다운 확인 없이 교전 시도 5회" |
| "바론 먹으면 됐나요?" | ❌ | "**상대 SCALING 조합** — 35분 이후 역전 위험. 지금 바론으로 엔딩 시도가 필수" |

---

## 11. Intent Inference ⭐ NEW (v3.0)

> **GPT 피드백**: "플레이어가 '왜 그랬는지'를 이해해야 올바른 피드백이 가능. 의도가 맞았는데 실행이 잘못된 경우 vs 의도 자체가 잘못된 경우를 구분"

### 11.1 의도 추론 시스템

```python
@dataclass
class PlayerIntent:
    timestamp_ms: int
    inferred_intent: str     # "KILL_ATTEMPT" | "RECALL" | "ROAM" | "FARM" | "OBJECTIVE" | "UNCLEAR"
    confidence: float        # 0.0~1.0
    evidence: list[str]      # 추론 근거
    intent_was_correct: bool # 의도 자체가 올바른가
    execution_quality: str   # "GOOD" | "PARTIAL" | "FAILED"
    feedback_type: str       # "WRONG_INTENT" | "WRONG_EXECUTION" | "BOTH_WRONG" | "CORRECT"

class IntentInferenceEngine:
    """
    동선 패턴 + 스킬 시퀀스 + 게임 상태로 플레이어 의도 추론
    """
    
    def infer_intent(
        self,
        timestamp_ms: int,
        snapshots: dict,
        events: list,
        player_id: int,
        window_sec: int = 10,
    ) -> PlayerIntent:
        
        # 이동 방향 분석
        movement = self._analyze_movement(timestamp_ms, snapshots, player_id, window_sec)
        
        # 스킬 사용 패턴
        skills_used = self._get_skills_in_window(timestamp_ms, events, player_id, window_sec)
        
        # 맵 위치 컨텍스트
        pos = self._get_position(snapshots, timestamp_ms, player_id)
        nearest_structure = self._nearest_structure(pos)
        
        # 추론 로직
        if movement.direction == "TOWARD_ENEMY" and len(skills_used) >= 2:
            if self._is_trade_pattern(skills_used):
                intent = "KILL_ATTEMPT"
                evidence = [f"적 방향 이동 + {', '.join(s['name'] for s in skills_used)} 사용"]
            else:
                intent = "POKE"
                evidence = ["Q/단발 스킬만 사용 — 포킹 패턴"]
        
        elif movement.direction == "TOWARD_TOWER" and movement.speed > 0.8:
            intent = "RECALL"
            evidence = ["타워 방향 고속 이동 — 귀환 준비"]
        
        elif movement.direction in ("TOWARD_DRAGON", "TOWARD_BARON"):
            intent = "OBJECTIVE"
            evidence = [f"{movement.direction} 방향 이동"]
        
        elif movement.direction == "TOWARD_SIDE_LANE":
            intent = "ROAM"
            evidence = ["사이드 레인 방향 이동"]
        
        else:
            intent = "FARM"
            evidence = ["미니언 근처 정지 + 이동"]
        
        return PlayerIntent(
            timestamp_ms=timestamp_ms,
            inferred_intent=intent,
            confidence=self._calc_confidence(movement, skills_used, intent),
            evidence=evidence,
        )
    
    def evaluate_intent(self, intent: PlayerIntent, game_state: GameState, comp: CompositionReport) -> PlayerIntent:
        """
        의도가 게임 상황에 비추어 올바른가를 평가
        """
        if intent.inferred_intent == "KILL_ATTEMPT":
            # 국면이 BEHIND이고 SCALING 조합이면 교전 의도 자체가 잘못됨
            if game_state.phase == "BEHIND" and comp.my_archetype == "SCALING":
                intent.intent_was_correct = False
                intent.feedback_type = "WRONG_INTENT"
                intent.evidence.append("BEHIND + SCALING 조합 — 교전 시도 자체가 손해")
            else:
                intent.intent_was_correct = True
        
        elif intent.inferred_intent == "ROAM":
            wave_state = self._get_wave_state_at(intent.timestamp_ms)
            if wave_state.state == "LOSING_WAVE":
                intent.intent_was_correct = False
                intent.feedback_type = "WRONG_INTENT"
                intent.evidence.append("로밍 전 웨이브가 LOSING — 라인 안정화가 우선")
        
        return intent
```

### 11.2 의도 기반 피드백 분류

```python
FEEDBACK_TEMPLATES = {
    "WRONG_INTENT": {
        "template": "이 시점 {intent} 시도 자체가 잘못된 선택입니다. {reason}",
        "focus": "의사결정 교정",
    },
    "WRONG_EXECUTION": {
        "template": "{intent}은 올바른 의도였습니다. 하지만 실행 방법이 잘못됐습니다. {execution_error}",
        "focus": "기술적 교정 (스킬 타이밍, 포지셔닝)",
    },
    "BOTH_WRONG": {
        "template": "의도({intent})도, 실행도 모두 개선이 필요합니다. {reason}",
        "focus": "전면 재검토",
    },
    "CORRECT": {
        "template": "{intent} 의도와 실행 모두 올바른 선택이었습니다.",
        "focus": "긍정 강화",
    },
}
```

### 11.3 Intent Inference가 가능하게 하는 코칭

| 상황 | 기존 피드백 | v3.0 피드백 |
|------|------------|------------|
| 킬 시도 실패 (의도는 맞았지만 실행 실수) | "이 시점에 교전하면 안 됩니다" | "**교전 의도는 맞았습니다.** 하지만 E → Q 대신 Q 선딜 후 E 연결이 필요했습니다. 스킬 순서 수정으로 해결 가능" |
| 킬 시도 실패 (의도 자체가 잘못) | "이 시점에 교전하면 안 됩니다" | "**교전 의도 자체가 잘못됐습니다.** BEHIND + SCALING 조합 — 이 단계는 팜으로 스케일해야 합니다. 교전 EV: -380골드" |

---

## 12. Player Modeling & Actionable Coaching ⭐ NEW (v3.0)

> **GPT 피드백**: "'다음 3게임 이것만 집중해서 해봐' — 개인화된 단기 과제 + 장기 성장 추적"

### 12.1 플레이어 약점 모델

```python
@dataclass
class PlayerModel:
    player_id: str
    updated_at: datetime
    
    # 반복 실수 패턴 (다경기 누적)
    recurring_mistakes: list[MistakePattern]
    
    # 통계적 약점 (챌린저 대비)
    stat_gaps: dict  # {"cs_per_min": -1.8, "vision_score": -12, "ward_placed": -4}
    
    # 강점
    strengths: list[str]
    
    # 현재 집중 과제 (최대 3개)
    current_focus: list[FocusTask]
    
    # 장기 성장 곡선
    growth_history: list[GrowthSnapshot]

@dataclass
class MistakePattern:
    mistake_type: str      # "wave_fight_while_behind", "no_vision_engage", etc.
    frequency: float       # 경기당 평균 발생 횟수
    severity: str          # "high" | "medium" | "low"
    trend: str             # "improving" | "stable" | "worsening"
    first_seen: datetime
    last_seen: datetime
    game_count: int        # 몇 경기에서 관찰됐는가

@dataclass
class FocusTask:
    title: str             # "웨이브 열세에서 교전 줄이기"
    description: str       # 구체적 행동 가이드
    metric: str            # 측정 지표
    target: float          # 목표 수치
    current: float         # 현재 수치
    progress: float        # 0.0~1.0
    deadline_games: int    # 다음 N게임 안에 달성 목표

class PlayerModelEngine:
    """다경기 데이터를 분석하여 플레이어 모델 업데이트"""
    
    async def update_model(self, db: AsyncSession, player_id: str, new_analysis: dict) -> PlayerModel:
        model = await self._load_or_create(db, player_id)
        
        # 새 경기의 실수를 기존 패턴에 누적
        for mistake in new_analysis["mistakes"]:
            self._update_mistake_pattern(model, mistake)
        
        # 통계 갭 업데이트
        self._update_stat_gaps(model, new_analysis["stats"], new_analysis["benchmark"])
        
        # 집중 과제 갱신 (진전이 있으면 업데이트, 완료 시 새 과제 부여)
        self._refresh_focus_tasks(model)
        
        await db.merge(model)
        return model
    
    def _refresh_focus_tasks(self, model: PlayerModel):
        """
        다음 3게임 집중 과제 선정 기준:
        1. 발생 빈도 높은 실수 (경기당 2회+)
        2. 심각도 높은 패턴 (death로 직결)
        3. 개선 가능성 높은 것 (trending: improving 아닌 것)
        """
        top_mistakes = sorted(
            model.recurring_mistakes,
            key=lambda m: m.frequency * (2 if m.severity == "high" else 1),
            reverse=True,
        )[:3]
        
        model.current_focus = [
            FocusTask(
                title=MISTAKE_TASK_MAP[m.mistake_type]["title"],
                description=MISTAKE_TASK_MAP[m.mistake_type]["description"],
                metric=MISTAKE_TASK_MAP[m.mistake_type]["metric"],
                target=MISTAKE_TASK_MAP[m.mistake_type]["target"],
                current=m.frequency,
                progress=max(0, 1 - m.frequency / (m.frequency + 1)),
                deadline_games=5,
            )
            for m in top_mistakes
        ]

MISTAKE_TASK_MAP = {
    "wave_fight_while_behind": {
        "title": "웨이브 열세 교전 줄이기",
        "description": "미니언 수 확인 후 — 내 미니언 < 적 미니언이면 교전 회피. 먼저 웨이브 정리 후 교전",
        "metric": "wave_behind_fight_count_per_game",
        "target": 0.5,
    },
    "no_vision_engage": {
        "title": "와드 없는 진입 줄이기",
        "description": "적 진영 진입 전 와드 1개 설치 확인. 정글러 MIA 30초 이상이면 타워 방향 유지",
        "metric": "no_vision_death_rate",
        "target": 0.2,
    },
    "late_recall": {
        "title": "골드 900+ 쌓이면 리콜",
        "description": "핵심 아이템 비용 이상 골드 보유 + 웨이브 CRASHING 상태 → 즉시 귀환",
        "metric": "wasteful_recall_rate",
        "target": 0.3,
    },
}
```

### 12.2 Player Model API 응답 예시

```json
{
  "player_id": "abc123",
  "games_analyzed": 47,
  "current_focus": [
    {
      "title": "웨이브 열세 교전 줄이기",
      "current": 2.1,
      "target": 0.5,
      "progress": 0.25,
      "trend": "stable",
      "description": "미니언 수 확인 → 내 미니언 < 적이면 후퇴 우선",
      "deadline_games": 5
    },
    {
      "title": "와드 없는 진입 줄이기",
      "current": 1.8,
      "target": 0.2,
      "progress": 0.10,
      "trend": "worsening",
      "description": "적 진영 진입 전 반드시 와드 1개 → 진입",
      "deadline_games": 5
    },
    {
      "title": "리콜 타이밍 최적화",
      "current": 0.69,
      "target": 0.8,
      "progress": 0.86,
      "trend": "improving",
      "description": "OPTIMAL 리콜 비율 70% 달성까지 유지",
      "deadline_games": 5
    }
  ],
  "strengths": ["스킬 적중률 상위 30%", "킬 후 매크로 판단 개선 중"],
  "stat_gaps": {
    "cs_per_min": { "player": 6.1, "challenger": 8.2, "gap": -2.1 },
    "vision_score": { "player": 14, "challenger": 28, "gap": -14 }
  },
  "growth_history": [
    { "date": "2026-03-01", "wave_fight_mistakes": 3.2, "vision_deaths": 2.1 },
    { "date": "2026-04-01", "wave_fight_mistakes": 2.1, "vision_deaths": 1.8 }
  ]
}
```

### 12.3 Player Modeling이 가능하게 하는 코칭

| 기존 | v3.0 Player Modeling |
|------|----------------------|
| "이 경기 7번 죽었습니다" | "최근 47경기 분석: **경기당 2.1회 웨이브 열세 교전** → 이 습관이 티어 상승의 핵심 장벽입니다" |
| (경기별 독립 분석) | "**다음 5게임 집중 과제**: ①와드 없는 진입 줄이기 ②CRASHING 직후 리콜 ③블루 사이드 CS 격차 줄이기" |
| (진전 확인 불가) | "리콜 타이밍 최적화: 3주 전 32% → 현재 69%. **목표 80%까지 86% 달성!**" |

---

## 13. Layer System

LLM에 전달하는 데이터를 계층적으로 정제하는 시스템입니다. 원본 데이터(수천만 토큰)를 직접 LLM에 넣지 않고, 필요한 깊이만큼만 꺼내서 전달합니다.

### 13.1 Layer 구조 (v3.0)

| Layer | 내용 | 크기 | LLM 포함 조건 | 포함 데이터 |
|-------|------|------|---------------|-------------|
| Layer 1 | 경기 전체 요약 | ~900 토큰 | 항상 포함 | KDA, CS, 승패, 핵심 문제 3가지 + Wave/Tempo/Macro 요약 + **게임 국면 타임라인 + 플레이어 모델 요약** |
| Layer 2 | 주요 이벤트 목록 | ~4,500 토큰 | 항상 포함 | 데스/킬/오브젝트 + 웨이브 컨텍스트 + 리콜 평가 + 매크로 판단 + **의도 추론 결과 + 예측 모델 경고** |
| Layer 3 | 장면별 상세 컨텍스트 | ~3,000 토큰 | 해당 장면 볼 때 | 초 단위 상태, 데미지 계산, 웨이브 상태, 파워 스파이크 + **Temporal Context (±30초 흐름) + 조합 컨텍스트** |
| Layer 4 | 원본 데이터 | DB 조회 | 구체적 질문 시 | 특정 틱의 미니언 수, 정글러 경로, 골드 히스토리 등 |
| Layer P | 플레이어 모델 | ~500 토큰 | 항상 포함 | 반복 실수 패턴, 현재 집중 과제, 통계 갭 (다경기 누적) |

### 13.2 Layer 생성 흐름 (v3.0)

```
[.rofl 파싱 완료 + Resilience Layer]
  ↓
[Context Analysis — 병렬 실행]
  ├── Wave Analysis Engine        → 웨이브 상태 타임라인 생성
  ├── Tempo & Recall Engine       → 리콜 평가 + 파워 스파이크 맵
  ├── Macro Decision Engine       → 이벤트별 매크로 판단
  ├── Predictive Simulation Engine → 주요 시점 미래 예측 + EV 계산  ← v3.0
  ├── Game State Engine           → 국면 분류 타임라인              ← v3.0
  ├── Composition Analyzer        → 조합 분석 (1회)                 ← v3.0
  └── Intent Inference            → 주요 이벤트 의도 추론            ← v3.0
  ↓
[Combat Analysis — Wave + GameState 컨텍스트 포함]
  → 킬각/시야/이벤트 + wave_state + game_state 보정
  ↓
Layer 4: 원본 데이터 전체 → PostgreSQL 저장
         (틱 데이터 + Wave 상태 타임라인 + 골드 히스토리 + 정글러 경로)
  ↓
Layer 3: 각 이벤트 ±15초 구간의 상세 컨텍스트 생성 → JSON 저장
    (초별 상태 + 데미지 계산 + 시나리오 분석 + 웨이브 상태 + 파워 스파이크
     + Temporal Context 30초 흐름 + 의도 추론 결과)               ← v3.0
  ↓
Layer 2: 이벤트 목록 + 패턴 분석 요약 → JSON 저장
    (데스/킬/오브젝트 + 리콜 평가 + 매크로 판단 + 실수 분류
     + 예측 경고 이벤트 + 의도 평가)                              ← v3.0
  ↓
Layer 1: 경기 전체 요약 → JSON 저장
    (결과, KDA, CS, 핵심 문제 3가지 + Wave/Tempo/Macro 요약
     + 게임 국면 타임라인 + 데이터 품질 등급)                      ← v3.0
  ↓
Layer P: 플레이어 모델 업데이트 → PostgreSQL 저장 (다경기 누적)    ← v3.0
    (반복 실수 패턴 + 집중 과제 갱신 + 성장 곡선 업데이트)
```

### 13.3 Layer 1 예시 (v3.0)

```json
{
  "match_summary": {
    "duration": "31:24",
    "result": "패배",
    "champion": "야스오",
    "role": "미드",
    "opponent": "아리",
    "kda": "3/7/4",
    "cs": 186,
    "cs_per_min": 5.9,
    "vision_score": 12,
    "damage_dealt": 18400,
    "tier": "골드2"
  },
  "verdict": "라인전 반복 데스가 핵심 패인",
  "top_issues": [
    "불리한 웨이브 상태에서 교전 시도 (데스 7회 중 5회 — LOSING_WAVE 상태)",
    "시야 관리 부족 (오브젝트 전 핵심 지점 미와드 4회)",
    "리콜 타이밍 비효율 (WASTEFUL 3회 — 평균 CS 7개 손실)"
  ],
  "wave_summary": {
    "avg_wave_state": "LOSING_WAVE 38% / EVEN 45% / FAST_PUSH 17%",
    "fights_in_losing_wave": "7회 데스 중 5회 LOSING_WAVE 상태",
    "optimal_recall_rate": "13회 리콜 중 OPTIMAL 3회 (23%)"
  },
  "macro_summary": {
    "post_kill_decisions_correct": "킬 후 최적 선택 7회 중 2회 (29%)",
    "objective_priority_errors": 2,
    "side_vs_teamfight_errors": 1
  },
  "game_state_summary": {
    "timeline": "EVEN(0~10분) → BEHIND(10~25분) → BEHIND(25~31분)",
    "turning_point": "10:00 3연속 데스 — 골드 역전",
    "macro_stance_recommended": "FARM_SCALE (SCALING 조합 + 골드 열세)",
    "macro_stance_actual": "계속 교전 시도 (PRESS)"
  },
  "composition_summary": {
    "my_archetype": "SCALING",
    "enemy_archetype": "ENGAGE",
    "win_condition": "35분 이후 아이템 3개 완성 후 교전 강세",
    "key_mistake": "BEHIND + SCALING 구간에서 ENGAGE 조합과 정면 교전 시도 5회"
  },
  "data_quality": "FULL",
  "player_model_update": "wave_behind_fight 패턴 +1 누적 (총 경기 47회 중 31회)"
}
```

### 13.4 Layer 2 예시

```json
{
  "events": [
    {
      "time": "4:12",
      "type": "solo_death",
      "title": "솔로 데스 #1",
      "severity": "critical",
      "short_summary": "체력 35% 상태에서 E 진입, 아리에게 킬",
      "fight_verdict": "RED — 4개 시나리오 전부 불리",
      "conditions": {
        "my_hp": "35%",
        "enemy_hp": "72%",
        "flash": "쿨다운",
        "vision": "없음",
        "jungler_mia": "35초"
      },
      "benchmark": "챌린저 92% 후퇴"
    }
  ],
  "patterns": {
    "deaths_with_low_hp_engage": "7회 데스 중 5회",
    "deaths_with_no_vision": "7회 데스 중 4회",
    "skill_accuracy": {
      "Q": "62% (챌린저 평균 71%)",
      "tornado_Q": "34% (챌린저 평균 48%)"
    }
  }
}
```

### 13.5 Layer 3 예시 (특정 장면)

```json
{
  "scene_time": "4:12",
  "scene_range": "4:00 ~ 4:15",
  "second_by_second": [
    {
      "time": "4:00",
      "my_hp": "42%", "my_mana": "35%",
      "enemy_hp": "74%",
      "wave": {"my_minions": 3, "enemy_minions": 5},
      "vision": {"my_wards": [], "enemy_jungler_visible": false}
    },
    {
      "time": "4:08",
      "action": "E 사용 (미니언 대시로 접근)"
    },
    {
      "time": "4:10",
      "action": "E-Q 콤보", "result": "Q 적중, 120 데미지",
      "enemy_reaction": "아리 E(매혹) → 적중"
    },
    {
      "time": "4:12",
      "result": "사망", "enemy_hp_remaining": "55%"
    }
  ],
  "damage_calculation": {
    "my_full_combo_damage": 280,
    "enemy_remaining_hp": 460,
    "can_kill": false,
    "enemy_full_combo_damage": 380,
    "my_hp_at_engage": 224,
    "will_die": true
  },
  "fight_scenarios": {
    "head_on": "패배 — 데미지 280 < 상대 잔여 460",
    "enemy_retreat": "패배 — E만 적중, Q 사거리 밖",
    "tower_lure": "사망 — 포탑 2대 + 반격으로 확정",
    "jungler_join": "확정 사망 — 8초 후 2v1"
  },
  "kill_window_nearby": {
    "time": "9:15",
    "reason": "아리 E 쿨다운 + 정글러 확인 + 체력 유리"
  }
}
```

### 13.6 LLM 컨텍스트 조립 규칙

| 질문 유형 | 사용 Layer | 토큰 수 | 예시 |
|-----------|-----------|---------|------|
| 경기 전체 질문 | L1 + L2 + LP | ~5,000 | "이 경기 뭐가 문제야?" |
| 특정 장면 질문 | L1 + L2 + L3 + LP | ~7,500 | "이 데스에서 킬각 있었어?" |
| 웨이브 관련 질문 | L1 + L2 + L3(wave) + LP | ~6,500 | "왜 싸우면 안 됐나요?" |
| 템포/리콜 질문 | L1 + L2 + L3(tempo) + LP | ~6,000 | "리콜 타이밍이 맞았나요?" |
| 매크로/국면 질문 | L1 + L2 + L3(macro) + LP | ~6,500 | "교전 이기고 왜 졌어요?" |
| 예측/경고 질문 | L1 + L2 + L3(predictive) + LP | ~6,000 | "갱 당할 걸 알 수 있었나요?" |
| 조합/매치업 질문 | L1 + L2 + L3(comp) + LP | ~5,500 | "이 조합에서 어떻게 해야 하나요?" |
| 내 습관 질문 | L1 + LP (전체) | ~4,000 | "내 반복 실수가 뭐예요?" |
| 구체적 수치 질문 | L1 + L2 + L3 + L4(쿼리) | ~8,000 | "3분 22초에 미니언 몇 마리?" |

> 경기 1건당 LLM 비용: 약 80~150원 (v3.0) vs 원본 전체 투입 시 50만원+ → 약 3,000배 절약

---

## 14. Coaching Script Generator

분석 결과를 기반으로 리플레이를 어떻게 재생할지에 대한 연출 스크립트를 생성합니다. 데스크탑 앱이 이 스크립트를 읽고 리플레이를 제어합니다.

### 14.1 Scene Phase 구조

| Phase | 시점 | 재생 속도 | 오버레이 |
|-------|------|-----------|----------|
| buildup | 이벤트 10~15초 전 | 1x | 상황 설명, 주의 포인트 하이라이트 |
| critical_moment | 이벤트 3초 전 | 0.25x | 슬로우모션, 체력바/쿨다운 오버레이 |
| explain | 이벤트 시점 | 정지 | 상세 피드백 패널 + 유저 인터랙션 대기 |

### 14.2 스크립트 데이터 구조

```typescript
interface CoachingScript {
  match_id: string;
  total_duration: number;  // 초
  scenes: Scene[];
}

interface Scene {
  id: string;
  title: string;                              // "솔로 데스 #1"
  severity: "critical" | "important" | "positive";
  phases: Phase[];
}

interface Phase {
  name: "buildup" | "critical_moment" | "explain";
  time: number;           // 초 (즉시 점프)
  speed: number;          // 0=정지, 0.25=슬로우, 1=실시간
  camera: CameraConfig;
  overlay: OverlayConfig;
}

interface CameraConfig {
  type: "player" | "focus_area";
  target?: string;        // 챔피언 이름
  position?: {x: number, y: number};
}

interface OverlayConfig {
  title?: string;
  text?: string;
  indicators?: Indicator[];  // 체력바, 쿨다운 등
  highlights?: Highlight[];  // 시야 범위, 위험 구역 등
  mistakes?: string[];
  benchmark?: string;
  tip?: string;
  buttons?: string[];        // "다시 보기", "대화하기", "다음 장면"
}
```

### 14.3 스크립트 자동 생성 로직

```python
def generate_coaching_script(match_analysis):
    scenes = []
    events = sorted(match_analysis.feedbacks, key=lambda e: e.time)
    
    for event in events:
        scene = {
            "id": event.id,
            "title": event.title,
            "severity": event.severity,
            "phases": [
                # 빌드업: 이벤트 15초 전으로 점프, 1배속
                {
                    "name": "buildup",
                    "time": event.time - 15,
                    "speed": 1.0,
                    "camera": {"type": "player"},
                    "overlay": generate_buildup_overlay(event)
                },
                # 결정적 순간: 3초 전, 0.25배속 슬로우모션
                {
                    "name": "critical_moment",
                    "time": event.time - 3,
                    "speed": 0.25,
                    "camera": {"type": "focus_area", "position": event.location},
                    "overlay": generate_moment_overlay(event)
                },
                # 설명: 정지 + 상세 피드백
                {
                    "name": "explain",
                    "time": event.time,
                    "speed": 0,
                    "overlay": generate_explanation_overlay(event)
                }
            ]
        }
        scenes.append(scene)
    
    return {"scenes": scenes}
```

### 14.4 피드백 우선순위 시스템 (v3.0 확장)

모든 실수를 다 보여주면 유저가 압도당하므로, 최대 6개만 선별합니다.

| 우선순위 | 포함 대상 |
|----------|-----------|
| Critical (최대 3개) | 데스로 이어진 실수, 오브젝트 손실, 궁/플래시 낭비 후 주요 싸움 |
| Important (최대 2개) | 반복적 스킬 빗나감, 불리한 교전 패턴, CS 누적 손해 |
| Positive (최대 1개) | 잘한 플레이 하이라이트 (강화 학습 효과) |

#### 14.4.1 Wave/Macro 이벤트 씬 유형 ⭐ v3.0

| 씬 유형 | 트리거 | buildup 설명 | explain 피드백 |
|---------|--------|--------------|----------------|
| wave_fight | LOSING_WAVE에서 교전 | 미니언 수 오버레이 표시 | "웨이브 열세에서 교전 — 미니언 7마리 어그로 추가 280 데미지" |
| recall_timing | WASTEFUL/DANGEROUS 리콜 | 타임라인 위 오브젝트 타이머 | "바론 85초 전 귀환 — 참여 실패 가능성" |
| macro_miss | 이벤트 후 최적 선택 미스 | 맵 상 오브젝트 위치 강조 | "킬 후 바론 먹었어야 — 스폰 38초, 팀 체력 양호" |
| predicted_gank | 예측 모델이 갱 감지 전 | 정글러 이동 경로 예측선 | "이 시점 후퇴했으면 갱 회피 가능" |

---

## 15. LLM Integration + Validation ⭐ v3.0

### 15.1 LLM의 역할

LLM은 계산기가 아니라 '코치'입니다. 복잡한 수학적 연산은 코드가 미리 수행하고, LLM은 그 결과를 사람이 이해할 수 있는 말로 변환합니다.

| 담당 | 내용 |
|------|------|
| 코드가 하는 것 | 거리 계산, 데미지 연산, 시야 판정, 킬각 시뮬레이션, 통계 비교 |
| LLM이 하는 것 | 계산 결과를 자연어로 설명, '왜 잘못인지' 맥락 설명, 개선 방법 제안, 유저 질문에 대화형 답변 |

### 15.2 대화형 코칭 (Chat API)

유저가 리플레이를 보면서 질문하면, 현재 장면의 컨텍스트가 자동으로 첨부됩니다.

```
유저 메시지 수신
  ↓
현재 보고 있는 장면 시간 확인
  ↓
Layer 1 + 2 (항상) + Layer 3 (현재 장면) 조립
  ↓
질문에 구체적 수치 필요? → Layer 4 DB 조회 추가
  ↓
시스템 프롬프트 + 컨텍스트 + 대화 히스토리 + 유저 질문
  ↓
LLM API 호출 → 응답 생성
  ↓
응답에 타임스탬프 추천이 있으면 → 앱에서 해당 시점으로 점프 가능
```

### 15.3 시스템 프롬프트 구조

```
역할: "당신은 챌린저 코치입니다"
규칙:
  1. 정확한 수치를 근거로 답변
  2. 유저 생각이 틀리면 데이터로 설명
  3. 맞는 부분은 인정
  4. 관련 다른 시점이 있으면 타임스탬프와 함께 제안
  5. 답변은 간결하게, 핵심만
  6. 해당 챔피언/매치업에 맞는 구체적 팁 포함
```

### 15.4 LLM 컨텍스트 조립 코드

```python
def build_llm_context(user_message, current_scene, match_data):
    context = {}
    
    # Layer 1: 항상 포함
    context["match_summary"] = match_data.layer1
    
    # Layer 2: 항상 포함
    context["all_events"] = match_data.layer2
    
    # Layer 3: 현재 장면만
    context["current_scene"] = match_data.get_layer3(current_scene.time)
    
    # Layer 4: 질문에 따라 동적 조회
    if needs_specific_data(user_message):
        context["queried_data"] = query_raw_data(
            user_message, current_scene.time, match_data.id
        )
    
    return context  # 총 ~6,000 토큰
```

### 15.5 LLM 답변 검증 레이어 ⭐ v3.0

LLM이 숫자를 환각(hallucination)하거나 데이터와 모순되는 답변을 낼 수 있습니다. 검증 레이어가 응답을 사전 검사합니다.

```python
class LLMAnswerValidator:
    """
    LLM 응답의 수치 주장을 실제 데이터와 대조 검증
    
    검증 규칙:
    1. 수치가 언급되면 Layer 데이터에서 확인
    2. 타임스탬프가 언급되면 실제 이벤트 존재 여부 확인
    3. 챔피언 수치(데미지, 쿨다운)가 언급되면 Data Dragon으로 검증
    """
    
    NUMERIC_PATTERNS = [
        r'(\d+)\s*데미지',
        r'(\d+)%\s*체력',
        r'(\d+)\s*골드',
        r'(\d+)\s*초\s*쿨다운',
        r'(\d+:\d+)',    # 타임스탬프
    ]
    
    async def validate(self, response: str, context: dict) -> ValidationResult:
        claims = self._extract_numeric_claims(response)
        errors = []
        
        for claim in claims:
            if claim.type == "timestamp":
                # 언급된 타임스탬프에 실제 이벤트가 있는가
                if not self._event_exists(claim.value, context["layer2"]):
                    errors.append(f"존재하지 않는 타임스탬프 언급: {claim.value}")
            
            elif claim.type == "damage":
                # 계산된 데미지와 오차 30% 이내인가
                calculated = context.get("damage_calculated", 0)
                if calculated and abs(claim.value - calculated) / calculated > 0.3:
                    errors.append(f"데미지 수치 불일치: LLM {claim.value} vs 계산 {calculated}")
        
        if errors:
            # 재생성 요청 (최대 2회)
            return ValidationResult(valid=False, errors=errors, regenerate=True)
        return ValidationResult(valid=True)
    
    async def chat_with_validation(self, message: str, context: dict, max_retries: int = 2):
        for attempt in range(max_retries + 1):
            response = await llm_client.chat(message, context)
            validation = await self.validate(response.message, context)
            
            if validation.valid:
                return response
            
            if attempt < max_retries:
                # 검증 실패 → 수정 지시와 함께 재생성
                correction_prompt = (
                    f"이전 답변에 오류가 있습니다: {', '.join(validation.errors)}\n"
                    f"데이터를 정확하게 참조하여 다시 답변해주세요."
                )
                context["correction"] = correction_prompt
        
        # 최종 실패 시 원본 반환 + 경고 플래그
        response.has_validation_warning = True
        return response
```

---

## 16. Desktop App

### 16.1 앱 기능

| 기능 | 설명 |
|------|------|
| 소환사 연동 | Riot ID 입력 → 전적 목록 표시 |
| 분석 요청 | 경기 선택 → 서버에 분석 요청 → 진행률 표시 |
| 텍스트 리포트 | 분석 완료 시 종합 피드백 리포트 표시 |
| 리플레이 코칭 | 롤 클라이언트에서 리플레이 자동 실행 + 오버레이 |
| 대화형 코칭 | 오버레이 내 챗봇 → LLM과 실시간 대화 |
| 시즌 대시보드 | 시즌 전체 성장 추이, 반복 실수 패턴 |

### 16.2 리플레이 오버레이 제어

```
사용 API:
- LCU API: 리플레이 실행
    POST /lol-replays/v1/rofls/{id}/watch
    
- Replay API (localhost:2999):
    POST /replay/playback → 시간 이동, 속도 조절, 일시정지
    POST /replay/render → 카메라 위치/대상 변경

오버레이 구현:
- Electron: transparent + alwaysOnTop + focusable:false 윈도우
- 롤 클라이언트 창 크기에 자동 맞춤
- 100ms 간격으로 리플레이 시간 폴링 → 오버레이 동기화
```

### 16.3 코칭 플레이어 동작 흐름

```
장면 목록에서 선택 (또는 자동 순차 재생)
  ↓
Phase: buildup → 해당 시간으로 즉시 점프, 1x 재생
  ↓
Phase: critical_moment → 0.25x 슬로우모션, 체력바/쿨다운 오버레이
  ↓
Phase: explain → 정지, 상세 피드백 패널 표시
  ├── [다시 보기] → buildup부터 다시
  ├── [대화하기] → 챗봇 열림, LLM과 대화
  └── [다음 장면] → 다음 Scene으로 즉시 점프
```

### 16.4 코칭 플레이어 코드 구조

```javascript
class CoachingPlayer {
    constructor(script) {
        this.script = script;
        this.currentScene = 0;
        this.replayAPI = "https://127.0.0.1:2999";
    }

    async play() {
        for (let i = 0; i < this.script.scenes.length; i++) {
            this.currentScene = i;
            const scene = this.script.scenes[i];
            
            for (const phase of scene.phases) {
                await this.seekTo(phase.time);        // 즉시 점프
                await this.setCamera(phase.camera);
                await this.setSpeed(phase.speed);
                this.showOverlay(phase.overlay);

                if (phase.speed === 0) {
                    const action = await this.waitForButton();
                    if (action === "rewind") { i--; break; }
                    if (action === "chat") { await this.openChat(scene); }
                } else {
                    await this.waitUntilTime(this.getNextPhaseTime(scene, phase));
                }
            }
        }
        this.showSummary();
    }

    async seekTo(time) {
        await fetch(`${this.replayAPI}/replay/playback`, {
            method: "POST",
            body: JSON.stringify({ time })
        });
    }

    async setSpeed(speed) {
        await fetch(`${this.replayAPI}/replay/playback`, {
            method: "POST",
            body: JSON.stringify({ paused: speed === 0, speed: speed || 1 })
        });
    }

    async setCamera(camera) {
        const body = camera.type === "player"
            ? { selectionName: this.playerChampion, cameraAttached: true }
            : { cameraPosition: camera.position, cameraAttached: false };
        
        await fetch(`${this.replayAPI}/replay/render`, {
            method: "POST",
            body: JSON.stringify(body)
        });
    }
}
```

---

## 17. Infrastructure

### 17.1 인프라 구성

| 컴포넌트 | 기술 | 역할 | 배포 |
|----------|------|------|------|
| API Server | FastAPI (Python) | 유저 요청, 인증, 분석 결과 제공 | Serverless (Lambda) 또는 ECS |
| Analysis Worker | Python + Celery | .rofl 파싱, 데미지 계산, Layer 생성 | ECS 또는 K8s (CPU) |
| .rofl Downloader | Windows VM + LoL Client | LCU API로 .rofl 자동 다운로드 | EC2 Windows 인스턴스 |
| Database | PostgreSQL | 유저, 분석 결과, 벤치마크, 원본 데이터 | RDS |
| Cache/Queue | Redis | 작업 큐 (Celery), 세션 캐시 | ElastiCache |
| File Storage | S3 / MinIO | .rofl 임시 저장 | S3 |
| Frontend | Next.js (React) | 웹 대시보드, 리포트 뷰어 | Vercel 또는 CloudFront |
| Desktop App | Electron / Tauri | 리플레이 오버레이 + 챗봇 | 유저 PC 설치 |

### 17.2 단계별 인프라 확장

| 단계 | 일일 유저 | 인프라 | 예상 비용 |
|------|-----------|--------|-----------|
| Phase 1 (MVP) | ~100명/일 | Oracle Cloud 무료 + Vercel | 월 0원 |
| Phase 2 (성장) | ~1,000명/일 | AWS ECS + RDS + S3 | 월 10~30만원 |
| Phase 3 (확장) | ~10,000명/일 | K8s 클러스터 + Auto Scaling | 월 50~100만원 |
| Phase 4 (대규모) | ~100,000명/일 | 멀티 리전 + CDN + DB 샤딩 | 월 300만원+ |

---

## 18. Development Roadmap

| 단계 | 기간 | 목표 | 주요 작업 |
|------|------|------|-----------|
| Phase 1 | 2~3주 | 기반 구축 | Riot API 연동, .rofl 파싱 POC, Data Dragon 로드, 기본 웹 UI |
| Phase 2 | 3~4주 | Combat 엔진 | 데미지 계산 엔진, 킬각 시뮬레이션, 시야 장악 분석, 실수 감지 |
| Phase 3 | 2~3주 | Layer + LLM | Layer 1~4 생성기, LLM 연동, 텍스트 피드백 생성 |
| Phase 4 | 2~3주 | **Wave Engine** | 웨이브 상태 감지, 미니언 손실 계산, Wave × Combat 통합 |
| Phase 5 | 2~3주 | **Tempo Engine** | 리콜 타이밍 평가, 파워 스파이크 시스템, Tempo Layer 연동 |
| Phase 6 | 2~3주 | **Macro Engine** | 오브젝트 선택 로직, 사이드 vs 한타 판단, Macro Layer 연동 |
| Phase 7 | 2~3주 | 벤치마크 | 챌린저 TOP 100 자동 수집, 매치업별 통계 DB, 비교 분석 |
| Phase 8 | 3~4주 | 데스크탑 앱 | Electron 앱, 리플레이 오버레이, 코칭 스크립트 플레이어 |
| Phase 9 | 2~3주 | 대화형 코칭 | 챗봇 UI, 실시간 LLM 대화, Wave/Macro 컨텍스트 연동 |
| Phase 10 | 2~3주 | 고도화 | 시즌 대시보드, 성장 추이, CI/CD, 모니터링 |
| Phase 11 | 2~3주 | **Predictive Engine** | 10~20초 예측 시뮬레이션, 갱 경고, EV 모델 |
| Phase 12 | 2~3주 | **Game State Engine** | 앞섬/비김/뒤짐 국면 분류, 스노우볼 추적 |
| Phase 13 | 2~3주 | **Composition Analyzer** | 챔피언 조합/매치업 이해, 국면별 강약점 |
| Phase 14 | 2~3주 | **Intent Inference** | 동선/스킬 시퀀스 기반 의도 추론 |
| Phase 15 | 3~4주 | **Player Modeling** | 개인 약점 DB, 다음 3게임 집중 과제 코칭 |

> 총 예상 개발 기간: 약 35~45주 (8~11개월)  
> Phase 1~3까지 완료 시 Combat 기반 MVP 출시 가능 (7~10주)  
> Phase 1~6까지 완료 시 완전한 v2.0 분석 엔진 완성 (13~18주)  
> Phase 1~15까지 완료 시 완전한 v3.0 AI 코치 완성 (35~45주)

---

## 19. Tech Stack

| 영역 | 기술 |
|------|------|
| Backend | Python 3.11+, FastAPI, Celery, SQLAlchemy |
| Frontend (Web) | Next.js (React), TypeScript, Tailwind CSS |
| Desktop App | Electron 또는 Tauri (Rust) |
| Database | PostgreSQL 16, Redis 7 |
| LLM | Claude API (Anthropic) 또는 GPT-4 API (OpenAI) |
| Game Data | Riot API, LCU API, Replay API, Data Dragon |
| Infra | AWS (ECS, RDS, S3, Lambda) 또는 Oracle Cloud (초기) |
| CI/CD | GitHub Actions → Docker → ECR → ECS/K8s |
| Monitoring | Prometheus + Grafana, Sentry (에러 추적) |
| IaC | Terraform (인프라 코드 관리) |

---

## 20. API Design

### 20.1 핵심 REST API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/auth/register` | 회원가입 |
| POST | `/api/auth/login` | 로그인 → JWT 발급 |
| POST | `/api/analysis/request` | 분석 요청 (소환사 이름 + 매치 ID) |
| GET | `/api/analysis/{id}/status` | 분석 진행 상태 조회 |
| GET | `/api/analysis/{id}/report` | 분석 결과 (Layer 1+2) 조회 |
| GET | `/api/analysis/{id}/scene/{sceneId}` | 특정 장면 상세 (Layer 3) 조회 |
| GET | `/api/analysis/{id}/script` | 코칭 스크립트 조회 |
| POST | `/api/analysis/{id}/chat` | 대화형 코칭 메시지 전송 |
| GET | `/api/analysis/{id}/raw` | 원본 데이터 쿼리 (Layer 4) |
| GET | `/api/benchmark/{champion}/{opponent}` | 매치업별 벤치마크 조회 |
| GET | `/api/summoner/{name}/season` | 시즌 전체 통계 조회 |
| GET | `/api/player/{id}/model` | 플레이어 모델 (약점 + 다음 과제) |

### 20.2 Chat API 요청/응답 구조

```json
// Request
{
  "message": "킬 딸 수 있지 않았나요?",
  "scene_time": 443.0,
  "match_id": "KR-7234567890",
  "chat_history": []
}

// Response
{
  "message": "상대 체력이 72%(460HP)였고 풀콤보 예상 데미지가 280이라 킬이 불가능했습니다...",
  "suggested_scenes": [
    {"time": 555.0, "label": "9:15 킬 가능했던 시점"}
  ]
}
```

### 20.3 Analysis Request/Response

```json
// POST /api/analysis/request
{
  "summoner_name": "Hide on bush",
  "tag": "KR1",
  "match_id": "KR-7234567890"
}

// Response
{
  "analysis_id": "anal_abc123",
  "status": "queued",
  "estimated_time": 90
}

// GET /api/analysis/anal_abc123/status
{
  "status": "processing",
  "progress": 65,
  "current_step": "combat_analysis"
}

// GET /api/analysis/anal_abc123/report
{
  "layer1": { ... },
  "layer2": { ... },
  "script": { ... },
  "benchmark_comparison": { ... }
}
```

### 20.4 WebSocket API — 실시간 분석 진행 ⭐ v3.0

```
WS /api/ws/analysis/{analysis_id}

클라이언트 → 서버:
  { "type": "subscribe" }

서버 → 클라이언트 (이벤트 스트림):
  { "type": "progress", "step": "wave_analysis", "pct": 35 }
  { "type": "progress", "step": "predictive_engine", "pct": 60 }
  { "type": "complete", "analysis_id": "anal_abc123" }
  { "type": "error", "message": "파싱 실패 — FALLBACK 모드로 전환" }
```

---

## 프로젝트 디렉토리 구조 (제안)

```
lol-ai-coach/
├── README.md
├── docs/
│   └── architecture.md          # 이 문서
│
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 엔트리포인트
│   │   ├── api/
│   │   │   ├── analysis.py      # 분석 API 라우터
│   │   │   ├── chat.py          # 대화형 코칭 API
│   │   │   ├── benchmark.py     # 벤치마크 API
│   │   │   └── summoner.py      # 소환사 조회 API
│   │   ├── core/
│   │   │   ├── config.py        # 환경설정
│   │   │   ├── database.py      # DB 연결
│   │   │   └── riot_client.py   # Riot API 클라이언트
│   │   ├── parser/
│   │   │   ├── rofl_parser.py   # .rofl 파일 파서
│   │   │   ├── metadata.py      # 메타데이터 추출
│   │   │   └── chunk_decoder.py # 청크 데이터 디코더
│   │   ├── analysis/
│   │   │   ├── combat_engine.py # 데미지 계산 엔진 (Wave 컨텍스트 통합)
│   │   │   ├── damage_calc.py   # 데미지 공식 구현
│   │   │   ├── vision_engine.py # 시야 장악 분석 엔진 (v2.0)
│   │   │   ├── event_detector.py # 이벤트/실수 감지 (Wave/Tempo/Macro 실수 포함)
│   │   │   ├── kill_window.py   # 킬각 탐색기
│   │   │   └── fight_simulator.py # 교전 시뮬레이션
│   │   ├── wave/                          # ⭐ NEW — Wave Analysis Engine
│   │   │   ├── wave_engine.py             # Wave 상태 감지 메인
│   │   │   ├── wave_state.py              # WaveState 데이터클래스 + 분류 로직
│   │   │   ├── minion_tracker.py          # 미니언 손실 계산기
│   │   │   └── wave_combat_integrator.py  # Wave × Combat 통합
│   │   ├── tempo/                         # ⭐ NEW — Tempo & Recall Engine
│   │   │   ├── tempo_engine.py            # Tempo 분석 메인
│   │   │   ├── recall_evaluator.py        # 리콜 타이밍 평가
│   │   │   ├── power_spike.py             # 챔피언별 파워 스파이크 DB
│   │   │   └── item_tracker.py            # 아이템 완성 타이밍 추적
│   │   ├── macro/                         # ⭐ NEW — Macro Decision Engine
│   │   │   ├── macro_engine.py            # 매크로 판단 메인
│   │   │   ├── objective_evaluator.py     # 오브젝트 우선순위 계산
│   │   │   ├── side_vs_teamfight.py       # 사이드 vs 한타 판단
│   │   │   └── rotation_analyzer.py       # 로테이션 평가
│   │   ├── predictive/                    # ⭐ v3.0 — Predictive Simulation Engine
│   │   │   ├── predictive_engine.py       # 미래 예측 메인
│   │   │   ├── gank_predictor.py          # 갱 위험 예측
│   │   │   ├── ev_model.py                # 기대값(EV) 계산 모델
│   │   │   └── kill_window_predictor.py   # 미래 킬 창 예측
│   │   ├── gamestate/                     # ⭐ v3.0 — Game State Engine
│   │   │   ├── game_state_engine.py       # 국면 분류 메인
│   │   │   ├── gold_tracker.py            # 팀 골드 리드 추적
│   │   │   └── snowball_analyzer.py       # 스노우볼 곡선 분석
│   │   ├── composition/                   # ⭐ v3.0 — Draft & Composition Analyzer
│   │   │   ├── composition_analyzer.py    # 팀 조합 분류
│   │   │   ├── matchup_database.py        # 매치업 데이터 DB
│   │   │   └── comp_archetypes.py         # 조합 유형 정의
│   │   ├── intent/                        # ⭐ v3.0 — Intent Inference
│   │   │   ├── intent_engine.py           # 의도 추론 메인
│   │   │   ├── movement_analyzer.py       # 동선 패턴 분석
│   │   │   └── skill_sequence_analyzer.py # 스킬 시퀀스 분석
│   │   ├── player_model/                  # ⭐ v3.0 — Player Modeling
│   │   │   ├── player_model_engine.py     # 플레이어 모델 업데이트
│   │   │   ├── mistake_tracker.py         # 반복 실수 패턴 추적
│   │   │   ├── focus_task_generator.py    # 집중 과제 생성
│   │   │   └── growth_tracker.py          # 성장 곡선 추적
│   │   ├── layer/
│   │   │   ├── layer_generator.py # Layer 1~4 생성기
│   │   │   ├── layer1_summary.py
│   │   │   ├── layer2_events.py
│   │   │   ├── layer3_scene.py
│   │   │   └── layer4_raw.py
│   │   ├── coaching/
│   │   │   ├── script_generator.py # 코칭 스크립트 생성
│   │   │   ├── llm_coach.py       # LLM 연동
│   │   │   └── prompt_builder.py  # 프롬프트 조립
│   │   ├── benchmark/
│   │   │   ├── collector.py       # 챌린저 데이터 수집
│   │   │   ├── statistics.py      # 매치업별 통계
│   │   │   └── comparator.py      # 유저 vs 벤치마크 비교
│   │   ├── game_data/
│   │   │   ├── data_dragon.py     # Data Dragon 로더
│   │   │   ├── champions.py       # 챔피언 데이터
│   │   │   ├── items.py           # 아이템 데이터
│   │   │   ├── runes.py           # 룬 데이터
│   │   │   └── patch_updater.py   # 패치 자동 갱신
│   │   ├── models/
│   │   │   ├── match.py           # 매치 모델
│   │   │   ├── analysis.py        # 분석 결과 모델
│   │   │   ├── player.py          # 플레이어 모델
│   │   │   ├── benchmark.py       # 벤치마크 모델
│   │   │   └── player_model.py    # 플레이어 모델링 (v3.0)
│   │   └── workers/
│   │       ├── analysis_worker.py # Celery 분석 워커
│   │       └── download_worker.py # .rofl 다운로드 워커
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── downloader/
│   ├── lcu_client.py             # LCU API 클라이언트
│   ├── auto_login.py             # 자동 로그인
│   ├── replay_downloader.py      # .rofl 다운로드 자동화
│   └── Dockerfile.windows        # Windows VM용
│
├── frontend/
│   ├── src/
│   │   ├── app/                   # Next.js 페이지
│   │   ├── components/
│   │   │   ├── AnalysisReport/    # 분석 리포트 컴포넌트
│   │   │   ├── MiniMapReplay/     # 2D 미니맵 리플레이어
│   │   │   ├── Timeline/          # 타임라인 컴포넌트
│   │   │   └── Dashboard/         # 시즌 대시보드
│   │   └── lib/
│   │       └── api.ts             # API 클라이언트
│   ├── package.json
│   └── Dockerfile
│
├── desktop/
│   ├── src/
│   │   ├── main/                  # Electron 메인 프로세스
│   │   │   ├── overlay.ts         # 오버레이 윈도우
│   │   │   ├── replay_control.ts  # Replay API 제어
│   │   │   └── lcu_bridge.ts      # LCU API 브릿지
│   │   ├── renderer/              # Electron 렌더러
│   │   │   ├── CoachingPlayer.tsx # 코칭 플레이어
│   │   │   ├── ChatBot.tsx        # 대화형 코칭 UI
│   │   │   └── FeedbackPanel.tsx  # 피드백 오버레이
│   │   └── preload/
│   ├── package.json
│   └── electron-builder.yml
│
├── infra/
│   ├── terraform/
│   │   ├── main.tf               # 메인 인프라
│   │   ├── ecs.tf                 # ECS 클러스터
│   │   ├── rds.tf                 # PostgreSQL
│   │   ├── s3.tf                  # 파일 스토리지
│   │   └── variables.tf
│   └── docker-compose.yml         # 로컬 개발용
│
└── .github/
    └── workflows/
        ├── ci.yml                 # 테스트 + 빌드
        └── deploy.yml             # 배포
```

---

## v3.0 설계 근거 — 종합 피드백 반영 요약

### 핵심 문제 재정의

| 분석 질문 | v1.0 | v2.0 | v3.0 |
|-----------|------|------|------|
| "교전에서 왜 졌나요?" | ✅ Combat Engine | ✅ | ✅ |
| "왜 그 교전이 생겼나요?" | ❌ | ✅ Wave Engine | ✅ |
| "리콜 타이밍이 맞았나요?" | ❌ | ✅ Tempo Engine | ✅ |
| "킬 후 왜 졌나요?" | ❌ | ✅ Macro Engine | ✅ |
| "갱 당할 걸 알 수 있었나요?" | ❌ | ❌ | ✅ Predictive Engine |
| "지금 게임이 이기고 있나요?" | ❌ | ❌ | ✅ Game State Engine |
| "이 조합에서 어떻게 해야 하나요?" | ❌ | ❌ | ✅ Composition Analyzer |
| "내가 왜 그랬는지 이해하나요?" | ❌ | ❌ | ✅ Intent Inference |
| "내 반복 실수가 뭔가요?" | ❌ | ❌ | ✅ Player Modeling |
| ".rofl 파싱 실패 시?" | 분석 불가 | 분석 불가 | ✅ Resilience → API 폴백 |

### 게임 구조 재분류 (v3.0)

```
LoL 경기 = 교전 (Combat) × 컨텍스트 (Context) × 예측 (Prediction) × 개인화 (Personalization)

v1.0 = "교전 결과"만 분석
v2.0 = "교전 결과" + "교전이 왜 생겼는가 (Wave/Macro)"
v3.0 = v2.0 + "앞으로 무슨 일이 생길까 (Predictive)" + "지금 게임 상태 (GameState)"
         + "이 조합에서 뭐가 맞는가 (Composition)" + "내가 왜 그랬는가 (Intent)"
         + "나만의 약점은 무엇인가 (PlayerModel)"
```

*End of Document — LoL AI Coach System Architecture v3.0*
