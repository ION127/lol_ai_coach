"""
전투 엔진 — 킬각/죽을각 판단.

이벤트 로그에서 교전 시점을 감지하고 fight_simulator로 결과를 예측한다.
"""
from __future__ import annotations

import logging

from app.analysis.utils import filter_events_in_window, get_snapshot_at

logger = logging.getLogger(__name__)

# 교전 감지 윈도우 (ms)
_FIGHT_WINDOW_MS = 10_000    # 10초 이내 킬 이벤트 → 동일 교전으로 묶음
_FIGHT_LOOKBACK_MS = 5_000   # 킬 이전 5초 스냅샷 기준


class CombatEngine:
    """
    GameContext → fight_verdicts, kill_windows 생성.

    인터페이스: run(ctx) -> {"fight_verdicts": dict, "kill_windows": list}
    """

    def run(self, ctx) -> dict:
        """
        Args:
            ctx: GameContext

        Returns:
            {"fight_verdicts": {ts: FightResult}, "kill_windows": [...]}
        """
        try:
            fight_verdicts, kill_windows = self._analyze(ctx)
            return {"fight_verdicts": fight_verdicts, "kill_windows": kill_windows}
        except Exception:
            logger.exception("CombatEngine 실패")
            return {"fight_verdicts": {}, "kill_windows": []}

    def _analyze(self, ctx) -> tuple[dict, list]:
        """교전 시점 감지 → 시뮬레이션"""
        from app.analysis.fight_simulator import simulate_full_fight

        kill_events = [
            e for e in ctx.events if e.get("type") == "CHAMPION_KILL"
        ]

        fight_verdicts: dict = {}
        kill_windows: list = []

        for event in kill_events:
            ts = event.get("timestamp", 0)
            data = event.get("data", event)

            killer_id = data.get("killerId", -1)
            victim_id = data.get("victimId", -1)

            # 내가 킬러 또는 피해자인 교전만 분석
            if ctx.player_id not in (killer_id, victim_id):
                continue

            if not ctx.has_snapshots():
                continue

            snap = get_snapshot_at(max(0, ts - _FIGHT_LOOKBACK_MS), ctx.snapshots)
            me = _build_fighter(snap, ctx.player_id)
            opponent_id = victim_id if killer_id == ctx.player_id else killer_id
            enemy = _build_fighter(snap, opponent_id)
            environment = _build_environment(snap, ctx.player_id)

            result = simulate_full_fight(me, enemy, environment)
            fight_verdicts[ts] = result

            # 킬 가능 창 기록
            if result.can_kill:
                kill_windows.append({
                    "timestamp_ms": ts,
                    "verdict": result.verdict,
                    "my_hp_remaining": result.my_hp_remaining,
                })

        return fight_verdicts, kill_windows


def _build_fighter(snap: dict, player_id: int) -> dict:
    """스냅샷에서 전투 스탯 추출"""
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            return {
                "hp": p.get("hp", 1000.0),
                "max_hp": p.get("max_hp", 1000.0),
                "ad": p.get("ad", 60.0),
                "ap": p.get("ap", 0.0),
                "armor": p.get("armor", 50.0),
                "mr": p.get("mr", 40.0),
                "attack_speed": p.get("attack_speed", 0.6),
                "armor_pen": p.get("armor_pen", 0.0),
            }
    # 기본값
    return {"hp": 1000.0, "max_hp": 1000.0, "ad": 60.0, "ap": 0.0,
            "armor": 50.0, "mr": 40.0, "attack_speed": 0.6, "armor_pen": 0.0}


def _build_environment(snap: dict, player_id: int) -> dict:
    """환경 dict 구성 (미니언 수, 정글러 합류 시간 등)"""
    # 내 팀 플레이어 팀 조회
    player_team = "blue"
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            player_team = p.get("team", "blue")
            break

    # 근처 적 미니언 수
    enemy_minions = [
        m for m in snap.get("minions", []) if m.get("team") != player_team
    ]

    return {
        "minion_count": len(enemy_minions),
        "jungler_arrival_sec": 5.0,  # TODO: 정글러 위치 기반 계산
    }
