"""
매크로 판단 엔진.

킬/오브젝트 이후 최선의 매크로 액션을 판단한다.
"""
from __future__ import annotations

import logging

from app.analysis.utils import filter_events_in_window, get_snapshot_at

logger = logging.getLogger(__name__)

# 오브젝트 점수 가중치
_OBJECTIVE_WEIGHTS = {
    "TOWER": 300,
    "INHIBITOR": 600,
    "DRAGON": 250,
    "BARON": 800,
    "HERALD": 400,
    "SIDE_LANE": 150,
}

# 킬 이후 매크로 판단 윈도우 (ms)
_POST_KILL_WINDOW_MS = 30_000  # 킬 후 30초


class MacroEngine:
    """
    GameContext → macro_decisions 생성.

    인터페이스: run(ctx) -> {"macro_decisions": list}
    """

    def run(self, ctx) -> dict:
        try:
            decisions = self._analyze(ctx)
            return {"macro_decisions": decisions}
        except Exception:
            logger.exception("MacroEngine 실패")
            return {"macro_decisions": []}

    def _analyze(self, ctx) -> list[dict]:
        """킬/오브젝트 이후 매크로 판단"""
        decisions = []

        # 킬 이벤트 기준 판단
        kill_events = [e for e in ctx.events if e.get("type") == "CHAMPION_KILL"]

        for event in kill_events:
            ts = event.get("timestamp", 0)
            data = event.get("data", event)

            # 내 팀 킬 여부 확인
            killer_id = data.get("killerId", -1)
            if killer_id != ctx.player_id:
                # 팀원 킬도 매크로 판단 (단순화: killer가 플레이어인 경우만)
                continue

            decision = self._decide_post_kill_action(ts, ctx)
            if decision:
                decisions.append(decision)

        return decisions

    def _decide_post_kill_action(self, kill_ts: int, ctx) -> dict | None:
        """킬 직후 최선의 매크로 액션 결정"""
        if not ctx.has_snapshots():
            return None

        snap = get_snapshot_at(kill_ts, ctx.snapshots)
        game_state = self._get_nearest_game_state(kill_ts, ctx)

        # 가용 오브젝트 점수 계산
        available = self._get_available_objectives(kill_ts, ctx)
        if not available:
            return None

        best_obj = max(available, key=lambda o: o["score"])
        actual = self._get_actual_action(kill_ts, ctx)

        suboptimal = (actual is not None and actual != best_obj["type"])

        return {
            "timestamp_ms": kill_ts,
            "recommended": best_obj["type"],
            "actual": actual,
            "suboptimal": suboptimal,
            "reason": f"킬 후 {best_obj['type']} 획득이 최선 (점수: {best_obj['score']})",
            "score": best_obj["score"],
        }

    def _get_available_objectives(self, ts: int, ctx) -> list[dict]:
        """현재 시점 획득 가능한 오브젝트 목록"""
        available = [
            {"type": "TOWER", "score": calc_objective_score("TOWER", ts)},
            {"type": "DRAGON", "score": calc_objective_score("DRAGON", ts)},
        ]

        # 바론은 20분 이후
        if ts >= 20 * 60 * 1000:
            available.append({"type": "BARON", "score": calc_objective_score("BARON", ts)})

        # 전령은 14분 이전
        if ts <= 14 * 60 * 1000:
            available.append({"type": "HERALD", "score": calc_objective_score("HERALD", ts)})

        return available

    def _get_actual_action(self, kill_ts: int, ctx) -> str | None:
        """킬 직후 실제로 한 액션 감지"""
        window_events = filter_events_in_window(
            ctx.events, kill_ts, kill_ts + _POST_KILL_WINDOW_MS
        )
        for event in window_events:
            etype = event.get("type", "")
            if etype == "BUILDING_KILL":
                return "TOWER"
            elif etype == "ELITE_MONSTER_KILL":
                data = event.get("data", event)
                monster = data.get("monsterType", "")
                if monster in ("DRAGON", "BARON_NASHOR", "RIFTHERALD"):
                    return monster.replace("_NASHOR", "").replace("RIFT", "")
        return None

    def _get_nearest_game_state(self, ts: int, ctx):
        """가장 가까운 GameState 반환"""
        if not ctx.game_state_timeline:
            return None
        nearest = min(
            ctx.game_state_timeline,
            key=lambda s: abs(s.timestamp_ms - ts),
            default=None,
        )
        return nearest


def calc_objective_score(obj_type: str, timestamp_ms: int) -> int:
    """
    오브젝트 점수 계산.

    Args:
        obj_type: "TOWER" | "DRAGON" | "BARON" | "HERALD" | "SIDE_LANE"
        timestamp_ms: 현재 게임 시간
    """
    base_score = _OBJECTIVE_WEIGHTS.get(obj_type, 100)

    # 게임 시간에 따른 가중치 조정
    game_min = timestamp_ms / 60_000
    if obj_type == "BARON" and game_min >= 20:
        base_score = int(base_score * 1.2)
    elif obj_type == "DRAGON" and game_min >= 25:
        base_score = int(base_score * 1.5)  # 드래곤 소울 근접

    return base_score
