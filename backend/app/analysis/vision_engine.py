"""
시야 장악도 계산 엔진 — stub.

TODO: 와드 시야 반경 계산 및 오브젝트 시야 준비도 계산 구현.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.analysis.utils import any_ward_covers, get_player_position, get_snapshot_at

logger = logging.getLogger(__name__)

# 오브젝트별 위치 (근사)
_OBJECTIVE_POSITIONS = {
    "BARON": {"x": 5007.0, "y": 10471.0},
    "DRAGON": {"x": 9866.0, "y": 4414.0},
    "HERALD": {"x": 5007.0, "y": 10471.0},
}

# 갱 위험 지점
_DANGER_ZONES = {
    "river_top": {"x": 4500.0, "y": 10500.0},
    "river_bot": {"x": 10500.0, "y": 4500.0},
    "jungle_top": {"x": 3500.0, "y": 8000.0},
    "jungle_bot": {"x": 11500.0, "y": 7000.0},
}


@dataclass
class VisionControlResult:
    """시야 분석 결과"""
    visible: bool
    vision_dominance: float           # 0.0~1.0
    vision_line_broken: bool
    objective_vision_ready: bool
    danger_unwarded: list[str] = field(default_factory=list)


class VisionEngine:
    """
    GameContext → vision 분석 (stub).

    실제 구현: 모든 스냅샷 타임스탬프에 대해 시야 분석 수행.
    현재: 스냅샷별 VisionControlResult 생성 (근사).
    """

    def run(self, ctx) -> dict:
        try:
            result = self._analyze(ctx)
            return {"vision_timeline": result}
        except Exception:
            logger.exception("VisionEngine 실패")
            return {"vision_timeline": {}}

    def _analyze(self, ctx) -> dict:
        if not ctx.has_snapshots():
            return {}

        timeline = {}
        for ts in ctx.snapshot_timestamps():
            snap = get_snapshot_at(ts, ctx.snapshots)
            result = calc_vision_dominance(
                ts,
                snap.get("my_wards", []),
                snap.get("enemy_wards", []),
                get_player_position(snap, ctx.player_id),
                ctx.events,
            )
            timeline[ts] = result

        return timeline


def calc_vision_dominance(
    timestamp: int,
    my_wards: list[dict],
    enemy_wards: list[dict],
    player_pos: dict,
    events: list[dict],
) -> VisionControlResult:
    """
    시야 장악도 계산.

    Args:
        timestamp: 현재 시점 (ms)
        my_wards: 내 팀 와드 목록
        enemy_wards: 적 팀 와드 목록
        player_pos: 플레이어 위치
        events: 전체 이벤트 (다음 오브젝트 예측용)
    """
    # 내 플레이어 시야 여부
    visible = any_ward_covers(my_wards, player_pos, radius=500.0)

    # 시야 장악도 = 내 와드 수 / (내 + 적) 와드 수
    total_wards = len(my_wards) + len(enemy_wards)
    vision_dominance = len(my_wards) / total_wards if total_wards > 0 else 0.5

    # 시야 라인 차단 여부 (플레이어 근처 적 와드)
    vision_line_broken = any_ward_covers(enemy_wards, player_pos, radius=1500.0)

    # 다음 오브젝트 시야 준비
    next_obj_pos = _get_next_objective_position(timestamp, events)
    objective_vision_ready = (
        any_ward_covers(my_wards, next_obj_pos) if next_obj_pos else False
    )

    # 위험 지점 미관측 목록
    danger_unwarded = _find_unwarded_danger_zones(player_pos, my_wards)

    return VisionControlResult(
        visible=visible,
        vision_dominance=vision_dominance,
        vision_line_broken=vision_line_broken,
        objective_vision_ready=objective_vision_ready,
        danger_unwarded=danger_unwarded,
    )


def _get_next_objective_position(
    timestamp: int, events: list[dict]
) -> dict | None:
    """다음 오브젝트 이벤트 위치 예측 (stub)"""
    # TODO: 바론/드래곤 스폰 타이밍 기반 예측
    for event in events:
        if event.get("timestamp", 0) > timestamp:
            etype = event.get("type", "")
            if etype == "ELITE_MONSTER_KILL":
                data = event.get("data", event)
                monster = data.get("monsterType", "")
                if monster in _OBJECTIVE_POSITIONS:
                    return _OBJECTIVE_POSITIONS[monster]
    return None


def _find_unwarded_danger_zones(
    player_pos: dict, my_wards: list[dict]
) -> list[str]:
    """플레이어 근처 위험 지점 중 와드 미설치 목록"""
    unwarded = []
    player_x = player_pos.get("x", 7500)

    # 플레이어 위치 기반 관련 위험 지점만 확인
    for zone_name, zone_pos in _DANGER_ZONES.items():
        # 플레이어와 너무 멀면 스킵 (5000 유닛)
        dist = abs(player_x - zone_pos["x"])
        if dist > 5000:
            continue
        if not any_ward_covers(my_wards, zone_pos):
            unwarded.append(zone_name)

    return unwarded
