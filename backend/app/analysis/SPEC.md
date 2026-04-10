# Analysis Module — SPEC

> `backend/app/analysis/`  
> 9개 분석 엔진 + 공통 유틸리티. 모든 엔진은 `run(ctx: GameContext) -> dict` 인터페이스를 따른다.

## 구현 진행 상황

| 파일 | 상태 | 비고 |
|------|------|------|
| `game_context.py` | ✅ 완료 | GameContext + run_analysis_pipeline() |
| `utils.py` | ✅ 완료 | 순수 함수 유틸리티 전체 |
| `game_state_engine.py` | ✅ 완료 | 골드/킬/타워/오브젝트 기반 국면 분류 |
| `wave_engine.py` | ✅ 완료 | 웨이브 상태 분석 (5초 샘플링) |
| `combat_engine.py` | ✅ 구현 | fight_simulator 연동, 킬 이벤트 기반 교전 분석 |
| `fight_simulator.py` | ✅ 구현 | DPS 모델 교전 시뮬레이션 (챔피언별 스탯 DB는 TODO) |
| `vision_engine.py` | ✅ 구현 | 와드 시야 계산, 위험 지점 미관측 탐지 |
| `tempo_engine.py` | ✅ 구현 | 리콜 타이밍 평가 (OPTIMAL/GOOD/WASTEFUL/DANGEROUS), 파워 스파이크 |
| `macro_engine.py` | ✅ 구현 | 킬 후 오브젝트 점수 계산, 최선 매크로 판단 |
| `predictive_engine.py` | ✅ 구현 | 갱 위험/킬각/오브젝트 창 예측 |
| `composition_engine.py` | ✅ 구현 | 팀 아키타입 분류, 구간별 유불리, 승패 조건 |
| `intent_engine.py` | ✅ 구현 | 의도 추론 (KILL_ATTEMPT/ROAM/FARM/RECALL), FALLBACK 모드 |
| `player_model_engine.py` | ✅ 구현 | EMA 기반 실수 패턴 누적, FocusTask 갱신 (DB 연동 TODO) |

> 마지막 업데이트: 2026-04-09
> 테스트: 75/75 (analysis), 전체 156/156

## SPEC 수정 이력

1. **`run_analysis_pipeline()` 시그니처 추가** — SPEC에 없었음
2. **Stage 4 수정**: "Layer 생성" 제거 — Layer 생성은 `layer/` 모듈 담당. Stage 4는 `PlayerModel pending_update` 준비만
3. **`player_model_engine` 동기화 명확화**: AsyncSession → `SyncSessionLocal` (Celery 동기 컨텍스트). "비동기 래핑" 표현 제거
4. **`FightResult` 단위 명확화**: `my_hp_remaining`/`enemy_hp_remaining` → HP 비율 (0.0~1.0)
5. **`JungleEngine` 제거**: Stage 1의 `[, JungleEngine]` — 미구현이며 파일 목록에도 없음. 일관성을 위해 Stage 1에서 제거

---

## 파일 목록

```
analysis/
├── game_context.py       # GameContext 데이터클래스 + merge() + run_analysis_pipeline()
├── utils.py              # 공통 유틸리티 함수 (모든 엔진이 import)
│
├── combat_engine.py      # §4 킬각/죽을각 판단
├── fight_simulator.py    # §4.4 교전 시뮬레이션 (simulate_full_fight 등)
├── vision_engine.py      # §4.5 시야 장악도 계산
│
├── wave_engine.py        # §5 웨이브 상태 분석
├── tempo_engine.py       # §6 템포/리콜 분석
├── macro_engine.py       # §7 매크로 판단
│
├── predictive_engine.py  # §8 미래 예측 (갱 위험, 오브젝트 창)
├── game_state_engine.py  # §9 게임 국면 분류
├── composition_engine.py # §10 조합/챔피언 이해
├── intent_engine.py      # §11 플레이어 의도 추론
│
└── player_model_engine.py # §12 다경기 개인화 모델 업데이트
```

---

## game_context.py

### GameContext — 파이프라인 공유 상태

```python
@dataclass
class GameContext:
    snapshots: dict        # {timestamp_ms: snap_dict}  ← parser 출력
    events:    list[dict]  # [{timestamp, type, data}]
    metadata:  dict        # champion_id, player_id, puuid, role, opponent 등
    data_quality: str      # "FULL" | "PARTIAL" | "FALLBACK"

    # 각 엔진이 채워넣는 결과 (None = 아직 미실행)
    wave_timeline:       dict | None = None   # {ts: WaveState}
    recall_evals:        list | None = None
    power_spikes:        list | None = None
    macro_decisions:     list | None = None
    fight_verdicts:      dict | None = None   # {ts: FightResult}
    kill_windows:        list | None = None
    predictive_warnings: list | None = None
    game_state_timeline: list | None = None   # list[GameState]
    composition:         "CompositionReport | None" = None
    intent_map:          dict | None = None   # {ts: PlayerIntent}
    player_model:        dict | None = None
    jungle_analysis:     "JungleAnalysis | None" = None
```

### 파이프라인 함수 시그니처

```python
def run_analysis_pipeline(ctx: GameContext) -> GameContext:
    """
    Celery 동기 컨텍스트에서 실행.
    concurrent.futures.ThreadPoolExecutor로 Stage 1/3 병렬 처리.
    """
```

### 파이프라인 실행 순서 (의존성 기반)

```
Stage 1 (병렬) ─ Wave, Tempo, Macro, Composition, GameState
Stage 2 (직렬) ─ CombatEngine  (wave_timeline 읽음)
Stage 3 (병렬) ─ PredictiveEngine, IntentEngine  (fight_verdicts 읽음)
Stage 4 (직렬) ─ PlayerModel pending_update 준비
                  (Layer 생성/DB 저장은 layer/ 모듈과 Celery 워커 담당)
```

---

## utils.py

> 모든 엔진이 공통으로 사용하는 순수 함수들. 사이드이펙트 없음, DB 접근 없음.

```python
def get_snapshot_at(timestamp_ms: int, snapshots: dict) -> dict:
    """이진탐색(bisect)으로 O(log n) 가장 가까운 스냅샷 반환"""

def euclidean_distance(a: dict, b: dict) -> float:
    """{"x": float, "y": float} 두 점 간 거리"""

def get_player_team(snap: dict, player_id: int) -> str:
    """snap['players']에서 player_id의 팀 반환 ("blue" | "red")"""

def get_player_position(snap: dict, player_id: int) -> dict:
    """snap['players']에서 player_id 위치 반환. 없으면 맵 중앙 {"x":7500,"y":7500}"""

def normalize_position(pos: dict) -> dict:
    """맵 좌표 (0~15000) → 정규화 (0.0~1.0)"""

def any_ward_covers(wards: list[dict], position: dict, radius: float = 900) -> bool:
    """wards 중 하나라도 position을 radius 내 커버하는지"""

def any_ward_covers_path(wards: list[dict], path: list[dict], radius: float = 900) -> bool:
    """경로 상 임의 지점이 와드 시야에 커버되는지"""

def estimate_crash_time(my_minions: list, enemy_minions: list) -> float:
    """미니언 수/타입 기반 웨이브 충돌 예상 시간(초)"""

def estimate_cs_loss_on_recall(wave_state: "WaveState", recall_duration_sec: float) -> int:
    """리콜 시 잃는 CS 추정치"""
```

---

## 엔진별 요약

### combat_engine.py (§4)
- `CombatEngine.run(ctx) -> dict`
- 이벤트 로그에서 교전 시점 감지 → `simulate_full_fight()` 호출 → `fight_verdicts` 생성
- `_build_environment(snap, player_id)` — 환경 dict 구성 (미니언 수, 정글러 합류 시간 등)
- 출력: `{"fight_verdicts": {ts: FightResult}, "kill_windows": [...]}`

### fight_simulator.py (§4.4)
- `simulate_full_fight(me, enemy, environment, wave_state=None) -> FightResult`
- `simulate_full_fight_basic(me, enemy, environment) -> FightResult`
- `calc_minion_damage(enemy_minion_count, fight_duration_sec, defender_armor, minion_type) -> float`
- `_estimate_fight_duration(me, enemy) -> float`
- `_calc_total_combo_damage(attacker, defender) -> float`
- `_determine_verdict(my_hp, enemy_hp) -> str`  # "GREEN"|"YELLOW"|"ORANGE"|"RED"

**FightResult 구조:**
```python
@dataclass
class FightResult:
    my_hp_remaining: float       # HP 비율 0.0~1.0 (절대값 아님)
    enemy_hp_remaining: float    # HP 비율 0.0~1.0
    can_kill: bool               # enemy_hp_remaining <= 0
    i_survive: bool              # my_hp_remaining > 0
    verdict: str                 # GREEN/YELLOW/ORANGE/RED
    fight_duration: float        # 교전 지속 시간(초)
    wave_context: "WaveState | None" = None
```

### vision_engine.py (§4.5)
- `calc_vision_dominance(timestamp, my_wards, enemy_wards, player_pos, events) -> VisionControlResult`
- `_get_next_objective_position(timestamp, events) -> dict | None`
- `_find_unwarded_danger_zones(player_pos, my_wards) -> list[str]`

**VisionControlResult:**
```python
@dataclass
class VisionControlResult:
    visible: bool
    vision_dominance: float          # 0.0~1.0
    vision_line_broken: bool
    objective_vision_ready: bool
    danger_unwarded: list[str]
```

### wave_engine.py (§5)
- `WaveEngine.run(ctx) -> dict`
- 5초 간격 샘플링 (360개 max, 54,000 전체 처리 방지)
- `detect_wave_state(timestamp_ms, snapshots, player_id) -> WaveState`
- 출력: `{"wave_timeline": {ts: WaveState}}`

**WaveState:**
```python
@dataclass
class WaveState:
    state: str            # FAST_PUSH/SLOW_PUSH/FREEZE/EVEN/CRASHING/LOSING_WAVE
    my_minion_count: int
    enemy_minion_count: int
    minion_advantage: int
    wave_position: float  # 0.0(내 타워)~1.0(적 타워)
    next_crash_estimate_sec: float
    cs_loss_if_recalled_now: int
    fight_risk_modifier: float  # 1.0=일반, >1.0=불리 패널티
```

### tempo_engine.py (§6)
- `TempoEngine.run(ctx) -> dict`
- 리콜 시점 평가: OPTIMAL/GOOD/WASTEFUL/DANGEROUS
- 파워 스파이크 타이밍 (아이템 완성 시점)
- 출력: `{"recall_evals": [...], "power_spikes": [...]}`

### macro_engine.py (§7)
- `MacroEngine.run(ctx) -> dict`
- 킬/오브젝트 이후 최선의 매크로 판단 (타워/드래곤/바론/사이드)
- 점수 계산: `calc_objective_score(obj, game_state)` → 최고점 오브젝트 선택
- 출력: `{"macro_decisions": [...]}`

### predictive_engine.py (§8)
- `PredictiveSimulationEngine.run(ctx) -> dict`
- 갱 위험 예측: `_predict_gank_risk(ts_ms, snap, snapshots, player_id)`
- 킬각 창 예측: `_predict_kill_window(ts_ms, snap, snapshots, player_id)`
- 오브젝트 창 예측: `_predict_objective_window(ts_ms, snap)`
- 정글러 이동 속도 테이블: `JUNGLER_SPEED_MAP`
- 출력: `{"predictive_warnings": [...]}`

### game_state_engine.py (§9)
- `GameStateEngine.run(ctx) -> dict`
- 국면 분류: AHEAD/EVEN/BEHIND/SNOWBALL/COMEBACK
- 골드 리드/타워 리드/킬 리드/드래곤 스택/바론 버프 종합
- 출력: `{"game_state_timeline": [GameState]}`

**GameState:**
```python
@dataclass
class GameState:
    timestamp_ms: int
    phase: str            # AHEAD/EVEN/BEHIND/SNOWBALL/COMEBACK
    gold_lead: int
    tower_lead: int
    kill_lead: int
    dragon_stacks: int
    baron_active: bool
    scaling_type: str     # PLAYER_SCALING/ENEMY_SCALING/EVEN
    confidence: float
```

### composition_engine.py (§10)
- `CompositionAnalyzer.run(ctx) -> dict`
- `analyze(my_team, enemy_team) -> CompositionReport`
- 팀 조합 아키타입: POKE/DIVE/SCALING/PEEL/ENGAGE/SPLIT
- 구간별 유불리: `_calc_phase_advantage()` → {"early": "PLAYER"|"ENEMY"|"EVEN", ...}
- 출력: `{"composition": CompositionReport}`

### intent_engine.py (§11)
- `IntentInferenceEngine.run(ctx) -> dict`
- 동선+스킬+이벤트로 의도 추론: KILL_ATTEMPT/ROAM/FARM/RECALL/UNCLEAR
- 의도 평가: WRONG_INTENT / WRONG_EXECUTION / BOTH_WRONG / CORRECT
- FALLBACK 모드: 위치 데이터 없을 때 이벤트만으로 추론
- 출력: `{"intent_map": {ts: PlayerIntent}}`

### player_model_engine.py (§12)
- `PlayerModelEngine.update_model(db, puuid, new_analysis) -> PlayerModel`
- SELECT ... FOR UPDATE 로 동시 업데이트 직렬화
- `_update_mistake_pattern(model, mistake)` — EMA 기반 빈도 누적
- `_update_stat_gaps(model, stats, benchmark)` — 챌린저 대비 차이 EMA 업데이트
- `_refresh_focus_tasks(model)` — 상위 3개 실수 → FocusTask 갱신
- **주의**: Celery 동기 컨텍스트 → `SyncSessionLocal` 사용 (AsyncSession/asyncio.run 금지)

---

## 데이터 흐름

```
ParseResult (parser/)
    ↓ game_context.py 에서 GameContext 생성
GameContext
    ↓ run_analysis_pipeline()
    ├─ Stage1: wave / tempo / macro / composition / game_state
    ├─ Stage2: combat (wave_timeline 읽음)
    ├─ Stage3: predictive / intent (fight_verdicts 읽음)
    └─ Stage4: 요약 dict → ctx.player_model["pending_update"]
GameContext (채워진 결과)
    ↓ layer/ 에서 Layer 1~4 생성
    ↓ coaching/ 에서 LLM 스크립트 생성
```
