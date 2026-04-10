"""
웨이브 상태 분석 엔진.

5초 간격으로 스냅샷을 샘플링하여 WaveState 타임라인을 생성한다.
스냅샷 없는 FALLBACK 모드에서는 빈 타임라인을 반환한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.analysis.utils import (
    estimate_crash_time,
    estimate_cs_loss_on_recall,
    get_snapshot_at,
)

logger = logging.getLogger(__name__)

# 샘플링 간격
_SAMPLE_INTERVAL_MS = 5_000   # 5초
_MAX_SAMPLES = 360            # 최대 360개 (30분 분량)

# 웨이브 상태 분류 임계값
_FAST_PUSH_THRESHOLD = 4      # 내 미니언이 적보다 4마리 이상 많음 → FAST_PUSH
_SLOW_PUSH_THRESHOLD = 2      # 2~3마리 앞섬 → SLOW_PUSH
_FREEZE_THRESHOLD = -2        # 적이 2마리 이상 많고 내 타워 근처 → FREEZE
_LOSING_WAVE_THRESHOLD = -4   # 적이 4마리 이상 많음 → LOSING_WAVE

# 웨이브 포지션 기준 (0.0 = 내 타워, 1.0 = 적 타워)
_POSITION_CRASH_THRESHOLD = 0.7   # 0.7 이상이면 CRASHING


@dataclass
class WaveState:
    """특정 시점의 웨이브 상태"""
    state: str                      # FAST_PUSH/SLOW_PUSH/FREEZE/EVEN/CRASHING/LOSING_WAVE
    my_minion_count: int
    enemy_minion_count: int
    minion_advantage: int           # 양수 = 내 팀 미니언 앞섬
    wave_position: float            # 0.0(내 타워)~1.0(적 타워)
    next_crash_estimate_sec: float  # 다음 웨이브 충돌까지 예상 시간(초)
    cs_loss_if_recalled_now: int    # 지금 리콜 시 잃는 CS
    fight_risk_modifier: float      # 1.0=일반, >1.0=불리 패널티


class WaveEngine:
    """
    GameContext → wave_timeline 생성.

    인터페이스: run(ctx) -> {"wave_timeline": {ts: WaveState}}
    """

    def run(self, ctx) -> dict:
        """
        Args:
            ctx: GameContext

        Returns:
            {"wave_timeline": {ts: WaveState}}
        """
        try:
            timeline = self._build_timeline(ctx)
            return {"wave_timeline": timeline}
        except Exception:
            logger.exception("WaveEngine 실패")
            return {"wave_timeline": {}}

    def _build_timeline(self, ctx) -> dict[int, WaveState]:
        """5초 간격 WaveState 타임라인 생성"""
        if not ctx.has_snapshots():
            return {}

        duration_ms = ctx.game_duration_ms()
        if duration_ms <= 0:
            return {}

        timeline: dict[int, WaveState] = {}
        sample_count = 0

        ts = _SAMPLE_INTERVAL_MS
        while ts <= duration_ms and sample_count < _MAX_SAMPLES:
            wave_state = detect_wave_state(ts, ctx.snapshots, ctx.player_id)
            timeline[ts] = wave_state
            ts += _SAMPLE_INTERVAL_MS
            sample_count += 1

        return timeline


def detect_wave_state(
    timestamp_ms: int, snapshots: dict, player_id: int
) -> WaveState:
    """
    특정 시점의 웨이브 상태를 스냅샷에서 분석.

    Args:
        timestamp_ms: 분석 시점 (ms)
        snapshots: {timestamp_ms: snap_dict}
        player_id: 플레이어 ID

    Returns:
        WaveState
    """
    snap = get_snapshot_at(timestamp_ms, snapshots)

    # 플레이어 정보 조회
    player = _find_player(snap, player_id)
    if player is None:
        return _default_wave_state()

    player_team = player.get("team", "blue")

    # 미니언 데이터 추출
    my_minions, enemy_minions = _extract_minions(snap, player_team)
    wave_pos = _calc_wave_position(snap, player_team)

    my_count = len(my_minions)
    enemy_count = len(enemy_minions)
    advantage = my_count - enemy_count

    # 충돌 예상 시간
    crash_sec = estimate_crash_time(my_minions, enemy_minions)

    # 웨이브 상태 분류
    state = _classify_wave(advantage, wave_pos)

    # 현재 WaveState 생성 (cs_loss 계산을 위한 임시)
    temp_wave = WaveState(
        state=state,
        my_minion_count=my_count,
        enemy_minion_count=enemy_count,
        minion_advantage=advantage,
        wave_position=wave_pos,
        next_crash_estimate_sec=crash_sec,
        cs_loss_if_recalled_now=0,
        fight_risk_modifier=_calc_fight_risk(state, wave_pos),
    )

    # 리콜 CS 손실 계산
    cs_loss = estimate_cs_loss_on_recall(temp_wave, recall_duration_sec=0.0)

    return WaveState(
        state=state,
        my_minion_count=my_count,
        enemy_minion_count=enemy_count,
        minion_advantage=advantage,
        wave_position=wave_pos,
        next_crash_estimate_sec=crash_sec,
        cs_loss_if_recalled_now=cs_loss,
        fight_risk_modifier=_calc_fight_risk(state, wave_pos),
    )


def _find_player(snap: dict, player_id: int) -> dict | None:
    """스냅샷에서 player_id로 플레이어 조회"""
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            return p
    return None


def _extract_minions(
    snap: dict, player_team: str
) -> tuple[list[dict], list[dict]]:
    """스냅샷에서 팀별 미니언 분리"""
    minions = snap.get("minions", [])
    my_minions = [m for m in minions if m.get("team") == player_team]
    enemy_minions = [m for m in minions if m.get("team") != player_team]
    return my_minions, enemy_minions


def _calc_wave_position(snap: dict, player_team: str) -> float:
    """
    미니언 위치 기반 웨이브 포지션 계산.
    0.0 = 내 타워, 1.0 = 적 타워.
    """
    minions = snap.get("minions", [])
    if not minions:
        return 0.5

    # 블루팀 기준: x 좌표가 클수록 적 타워에 가까움
    # 레드팀 기준: x 좌표가 작을수록 적 타워에 가까움
    positions = [
        m.get("position", {}).get("x", 7500)
        for m in minions
        if m.get("team") == player_team
    ]
    if not positions:
        return 0.5

    avg_x = sum(positions) / len(positions)
    # 0~15000 범위에서 정규화
    normalized = avg_x / 15000.0

    if player_team == "red":
        # 레드팀은 반전 (x가 작을수록 앞섬)
        normalized = 1.0 - normalized

    return max(0.0, min(1.0, normalized))


def _classify_wave(advantage: int, wave_pos: float) -> str:
    """미니언 수/위치 기반 웨이브 상태 분류"""
    if wave_pos >= _POSITION_CRASH_THRESHOLD:
        return "CRASHING"
    if advantage >= _FAST_PUSH_THRESHOLD:
        return "FAST_PUSH"
    if advantage >= _SLOW_PUSH_THRESHOLD:
        return "SLOW_PUSH"
    if advantage <= _LOSING_WAVE_THRESHOLD:
        return "LOSING_WAVE"
    if advantage <= _FREEZE_THRESHOLD and wave_pos <= 0.35:
        return "FREEZE"
    return "EVEN"


def _calc_fight_risk(state: str, wave_pos: float) -> float:
    """웨이브 상황에 따른 교전 위험도 배율"""
    if state == "LOSING_WAVE":
        return 1.5   # 미니언 불리 → 교전 불리
    if state == "FREEZE":
        return 1.4   # 프리즈 중 교전 위험
    if state == "CRASHING":
        return 0.9   # 웨이브 크래시 직후 교전 유리
    if state == "FAST_PUSH":
        return 0.95  # 웨이브 주도권 있음
    return 1.0


def _default_wave_state() -> WaveState:
    """데이터 없을 때 기본 WaveState"""
    return WaveState(
        state="EVEN",
        my_minion_count=0,
        enemy_minion_count=0,
        minion_advantage=0,
        wave_position=0.5,
        next_crash_estimate_sec=30.0,
        cs_loss_if_recalled_now=0,
        fight_risk_modifier=1.0,
    )
