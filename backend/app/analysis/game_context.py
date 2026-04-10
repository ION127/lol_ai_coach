"""
GameContext — 분석 파이프라인 공유 상태 + 파이프라인 오케스트레이터.

모든 엔진은 GameContext를 받아 결과를 ctx에 채워넣고 반환한다.
Celery 동기 컨텍스트에서 실행:
  - Stage 1/3: concurrent.futures.ThreadPoolExecutor로 병렬
  - Stage 2/4: 직렬
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.analysis.composition_engine import CompositionReport
    from app.analysis.game_state_engine import GameState
    from app.analysis.intent_engine import PlayerIntent
    from app.analysis.vision_engine import VisionControlResult
    from app.analysis.wave_engine import WaveState

logger = logging.getLogger(__name__)


@dataclass
class GameContext:
    """
    분석 파이프라인 전체에서 공유하는 상태 컨테이너.

    parser.ParseResult → GameContext 변환 후 run_analysis_pipeline() 에 전달.
    각 엔진은 해당 필드를 채워넣는다.

    주의: JSON 직렬화 시 dataclass가 아닌 dict로 변환 필요.
    """

    # ── 입력 데이터 (parser 출력) ─────────────────────────────────
    snapshots: dict           # {timestamp_ms: snap_dict}
    events: list[dict]        # [{timestamp, type, data}]
    metadata: dict            # champion_id, player_id, puuid, role, opponent 등
    data_quality: str         # "FULL" | "PARTIAL" | "FALLBACK"

    # ── Stage 1 결과 (Wave/Tempo/Macro/Composition/GameState) ────
    wave_timeline: dict | None = None          # {ts: WaveState}
    recall_evals: list | None = None
    power_spikes: list | None = None
    macro_decisions: list | None = None
    game_state_timeline: list | None = None    # list[GameState]
    composition: "CompositionReport | None" = None

    # ── Stage 2 결과 (CombatEngine) ──────────────────────────────
    fight_verdicts: dict | None = None         # {ts: FightResult}
    kill_windows: list | None = None

    # ── Stage 3 결과 (Predictive/Intent) ─────────────────────────
    predictive_warnings: list | None = None
    intent_map: dict | None = None             # {ts: PlayerIntent}

    # ── Stage 4 결과 (PlayerModel 업데이트용 집계) ───────────────
    player_model: dict | None = None           # {"pending_update": {...}}

    @classmethod
    def from_parse_result(cls, parse_result, metadata: dict | None = None) -> "GameContext":
        """
        parser.ParseResult → GameContext 변환.

        Args:
            parse_result: app.parser.models.ParseResult
            metadata: 추가 메타데이터 (champion_id, player_id, role 등)
        """
        merged_meta = dict(parse_result.metadata)
        if metadata:
            merged_meta.update(metadata)

        return cls(
            snapshots=parse_result.snapshots,
            events=parse_result.events,
            metadata=merged_meta,
            data_quality=parse_result.quality,
        )

    @property
    def player_id(self) -> int:
        return int(self.metadata.get("player_id", 0))

    @property
    def champion_id(self) -> int:
        return int(self.metadata.get("champion_id", 0))

    @property
    def role(self) -> str:
        return str(self.metadata.get("role", "UNKNOWN"))

    @property
    def puuid(self) -> str:
        return str(self.metadata.get("puuid", ""))

    def has_snapshots(self) -> bool:
        return bool(self.snapshots)

    def snapshot_timestamps(self) -> list[int]:
        return sorted(self.snapshots.keys())

    def game_duration_ms(self) -> int:
        """스냅샷 기준 게임 전체 시간 (ms)"""
        if not self.snapshots:
            if self.events:
                return max(e.get("timestamp", 0) for e in self.events)
            return 0
        return max(self.snapshots.keys())


# ── 파이프라인 오케스트레이터 ────────────────────────────────────
def run_analysis_pipeline(ctx: GameContext) -> GameContext:
    """
    분석 파이프라인 전체 실행.

    Celery 동기 컨텍스트에서 실행.
    ThreadPoolExecutor로 Stage 1/3 병렬 처리.

    Args:
        ctx: 입력 GameContext (snapshots, events, metadata, data_quality 채워진 상태)

    Returns:
        모든 엔진 결과가 채워진 GameContext
    """
    logger.info(
        "파이프라인 시작: quality=%s snapshots=%d events=%d",
        ctx.data_quality,
        len(ctx.snapshots),
        len(ctx.events),
    )

    # ── Stage 1: 병렬 ─────────────────────────────────────────────
    _run_stage1(ctx)

    # ── Stage 2: 직렬 (wave_timeline 의존) ───────────────────────
    _run_stage2(ctx)

    # ── Stage 3: 병렬 (fight_verdicts 의존) ──────────────────────
    _run_stage3(ctx)

    # ── Stage 4: PlayerModel pending_update 준비 ─────────────────
    _run_stage4(ctx)

    logger.info("파이프라인 완료")
    return ctx


def _run_parallel(ctx: GameContext, runners: list) -> None:
    """엔진 목록을 ThreadPoolExecutor로 병렬 실행"""
    if not runners:
        return
    with ThreadPoolExecutor(max_workers=len(runners)) as executor:
        futures = {executor.submit(fn, ctx): fn.__name__ for fn in runners}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("엔진 실패 (stage): %s", name)


def _run_stage1(ctx: GameContext) -> None:
    from app.analysis.composition_engine import CompositionEngine
    from app.analysis.game_state_engine import GameStateEngine
    from app.analysis.macro_engine import MacroEngine
    from app.analysis.tempo_engine import TempoEngine
    from app.analysis.wave_engine import WaveEngine

    def run_wave(c: GameContext) -> None:
        result = WaveEngine().run(c)
        c.wave_timeline = result.get("wave_timeline")

    def run_tempo(c: GameContext) -> None:
        result = TempoEngine().run(c)
        c.recall_evals = result.get("recall_evals")
        c.power_spikes = result.get("power_spikes")

    def run_macro(c: GameContext) -> None:
        result = MacroEngine().run(c)
        c.macro_decisions = result.get("macro_decisions")

    def run_composition(c: GameContext) -> None:
        result = CompositionEngine().run(c)
        c.composition = result.get("composition")

    def run_game_state(c: GameContext) -> None:
        result = GameStateEngine().run(c)
        c.game_state_timeline = result.get("game_state_timeline")

    _run_parallel(ctx, [run_wave, run_tempo, run_macro, run_composition, run_game_state])


def _run_stage2(ctx: GameContext) -> None:
    from app.analysis.combat_engine import CombatEngine

    try:
        result = CombatEngine().run(ctx)
        ctx.fight_verdicts = result.get("fight_verdicts")
        ctx.kill_windows = result.get("kill_windows")
    except Exception:
        logger.exception("CombatEngine 실패")


def _run_stage3(ctx: GameContext) -> None:
    from app.analysis.intent_engine import IntentEngine
    from app.analysis.predictive_engine import PredictiveEngine

    def run_predictive(c: GameContext) -> None:
        result = PredictiveEngine().run(c)
        c.predictive_warnings = result.get("predictive_warnings")

    def run_intent(c: GameContext) -> None:
        result = IntentEngine().run(c)
        c.intent_map = result.get("intent_map")

    _run_parallel(ctx, [run_predictive, run_intent])


def _run_stage4(ctx: GameContext) -> None:
    """PlayerModel 업데이트용 집계 데이터 준비 (DB 저장은 Celery 워커 담당)"""
    try:
        ctx.player_model = _build_player_model_update(ctx)
    except Exception:
        logger.exception("PlayerModel 집계 실패")
        ctx.player_model = {"pending_update": {}}


def _build_player_model_update(ctx: GameContext) -> dict:
    """
    각 엔진 결과에서 PlayerModel 업데이트에 필요한 데이터 집계.
    실제 DB 저장은 player_model_engine.update_model()에서 처리.
    """
    mistakes: list[dict] = []
    stat_gaps: dict = {}

    # 매크로 실수 집계
    for decision in ctx.macro_decisions or []:
        if decision.get("suboptimal"):
            mistakes.append({
                "type": "macro",
                "timestamp_ms": decision.get("timestamp_ms", 0),
                "description": decision.get("reason", ""),
            })

    # 경고 집계
    for warning in ctx.predictive_warnings or []:
        if warning.get("severity") in ("HIGH", "CRITICAL"):
            mistakes.append({
                "type": "positioning",
                "timestamp_ms": warning.get("timestamp_ms", 0),
                "description": warning.get("description", ""),
            })

    # 게임 상태에서 스탯 갭 집계 (마지막 GameState 기준)
    timeline = ctx.game_state_timeline or []
    if timeline:
        last_state = timeline[-1]
        stat_gaps = {
            "gold_lead": getattr(last_state, "gold_lead", 0),
            "kill_lead": getattr(last_state, "kill_lead", 0),
        }

    return {
        "pending_update": {
            "mistakes": mistakes,
            "stat_gaps": stat_gaps,
            "data_quality": ctx.data_quality,
            "game_duration_ms": ctx.game_duration_ms(),
        }
    }
