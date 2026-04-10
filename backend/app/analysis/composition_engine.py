"""
조합/챔피언 이해 엔진.

팀 조합 아키타입 분류 및 구간별 유불리 분석.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 챔피언 아키타입 매핑 (champion_id → archetype)
# TODO: 전체 챔피언 DB 연동
_CHAMPION_ARCHETYPE: dict[int, str] = {
    # SCALING
    67: "SCALING",   # Vayne
    96: "SCALING",   # Kog'Maw
    136: "SCALING",  # Aurelion Sol
    101: "SCALING",  # Xerath
    161: "SCALING",  # Vel'Koz
    # POKE
    51: "POKE",      # Caitlyn
    202: "POKE",     # Jhin
    15: "POKE",      # Sivir
    # ENGAGE
    12: "ENGAGE",    # Alistar
    54: "ENGAGE",    # Malphite
    89: "ENGAGE",    # Leona
    # DIVE
    59: "DIVE",      # Jarvan
    254: "DIVE",     # Vi
    64: "DIVE",      # Lee Sin
    # PEEL
    117: "PEEL",     # Lulu
    40: "PEEL",      # Janna
    37: "PEEL",      # Sona
    # SPLIT
    23: "SPLIT",     # Tryndamere
    75: "SPLIT",     # Nasus
    114: "SPLIT",    # Fiora
}

_DEFAULT_ARCHETYPE = "EVEN"


@dataclass
class CompositionReport:
    """팀 조합 분석 결과"""
    my_archetype: str                      # 내 팀 주 아키타입
    enemy_archetype: str                   # 적 팀 주 아키타입
    phase_advantage: dict[str, str] = field(default_factory=dict)
    # {"early": "PLAYER"|"ENEMY"|"EVEN", "mid": ..., "late": ...}
    win_condition: str = ""                # 승리 조건 설명
    lose_condition: str = ""              # 패배 조건 설명


class CompositionEngine:
    """
    GameContext → composition 생성.

    인터페이스: run(ctx) -> {"composition": CompositionReport}
    """

    def run(self, ctx) -> dict:
        try:
            report = self._analyze(ctx)
            return {"composition": report}
        except Exception:
            logger.exception("CompositionEngine 실패")
            return {"composition": None}

    def _analyze(self, ctx) -> CompositionReport:
        my_team, enemy_team = self._extract_teams(ctx)
        return analyze(my_team, enemy_team)

    def _extract_teams(self, ctx) -> tuple[list[int], list[int]]:
        """스냅샷에서 팀 구성 추출"""
        if not ctx.has_snapshots():
            return [ctx.champion_id], []

        from app.analysis.utils import get_snapshot_at
        first_ts = min(ctx.snapshots.keys())
        snap = get_snapshot_at(first_ts, ctx.snapshots)

        # 플레이어 팀 파악
        player_team = "blue"
        for p in snap.get("players", []):
            if p.get("id") == ctx.player_id:
                player_team = p.get("team", "blue")
                break

        my_team = [
            p.get("champion_id", 0)
            for p in snap.get("players", [])
            if p.get("team") == player_team
        ]
        enemy_team = [
            p.get("champion_id", 0)
            for p in snap.get("players", [])
            if p.get("team") != player_team
        ]

        return my_team, enemy_team


def analyze(my_team: list[int], enemy_team: list[int]) -> CompositionReport:
    """
    팀 조합 아키타입 분석.

    Args:
        my_team: 내 팀 챔피언 ID 목록
        enemy_team: 적 팀 챔피언 ID 목록

    Returns:
        CompositionReport
    """
    my_archetype = _determine_team_archetype(my_team)
    enemy_archetype = _determine_team_archetype(enemy_team)

    phase_advantage = _calc_phase_advantage(my_archetype, enemy_archetype)
    win_cond, lose_cond = _determine_conditions(my_archetype, enemy_archetype)

    return CompositionReport(
        my_archetype=my_archetype,
        enemy_archetype=enemy_archetype,
        phase_advantage=phase_advantage,
        win_condition=win_cond,
        lose_condition=lose_cond,
    )


def _determine_team_archetype(champion_ids: list[int]) -> str:
    """팀 챔피언 목록에서 주요 아키타입 결정"""
    if not champion_ids:
        return _DEFAULT_ARCHETYPE

    archetype_counts: dict[str, int] = {}
    for cid in champion_ids:
        archetype = _CHAMPION_ARCHETYPE.get(cid, _DEFAULT_ARCHETYPE)
        archetype_counts[archetype] = archetype_counts.get(archetype, 0) + 1

    # 가장 많은 아키타입 선택
    best = max(archetype_counts, key=lambda k: archetype_counts[k])
    return best


def _calc_phase_advantage(
    my_archetype: str, enemy_archetype: str
) -> dict[str, str]:
    """구간별 유불리 계산"""
    # 아키타입별 강세 구간
    _early_strong = {"DIVE", "ENGAGE", "POKE"}
    _late_strong = {"SCALING", "PEEL"}

    early = _compare_advantage(my_archetype, enemy_archetype, _early_strong)
    late = _compare_advantage(my_archetype, enemy_archetype, _late_strong)

    # 미드는 중간
    mid = "PLAYER" if early == "PLAYER" and late == "PLAYER" else (
        "ENEMY" if early == "ENEMY" and late == "ENEMY" else "EVEN"
    )

    return {"early": early, "mid": mid, "late": late}


def _compare_advantage(
    my: str, enemy: str, strong_set: set
) -> str:
    """두 아키타입 중 강세 구간 비교"""
    my_strong = my in strong_set
    enemy_strong = enemy in strong_set
    if my_strong and not enemy_strong:
        return "PLAYER"
    if enemy_strong and not my_strong:
        return "ENEMY"
    return "EVEN"


def _determine_conditions(
    my_archetype: str, enemy_archetype: str
) -> tuple[str, str]:
    """승리/패배 조건 텍스트"""
    win_conditions = {
        "SCALING": "후반 스케일링 후 한타 우위 점유",
        "POKE": "초반 CS 이점 및 체력 이득",
        "ENGAGE": "적 합류 전 선제 이니시에이트",
        "DIVE": "다이브로 백라인 제거",
        "PEEL": "딜러 생존 유지하여 한타 지속",
        "SPLIT": "사이드 레인 압박 후 오브젝트 전환",
        "EVEN": "전반적 운영 우위",
    }
    lose_conditions = {
        "SCALING": "후반 도달 전 게임 종료 위험",
        "POKE": "다이브 및 돌격 조합에 취약",
        "ENGAGE": "시야 관리 실패 시 역이니시 위험",
        "DIVE": "펠 조합에 백라인 다이브 저지 위험",
        "PEEL": "스플릿 압박에 분산되면 불리",
        "SPLIT": "한타 합류 지연 시 집단전 불리",
        "EVEN": "상황별 대응 실패",
    }
    return (
        win_conditions.get(my_archetype, ""),
        lose_conditions.get(my_archetype, ""),
    )
