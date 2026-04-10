"""
교전 시뮬레이터 — stub.

TODO: 챔피언 스탯 데이터 로드 후 실제 시뮬레이션 구현.
현재는 기본 근사 모델만 제공.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.analysis.wave_engine import WaveState

logger = logging.getLogger(__name__)


@dataclass
class FightResult:
    """교전 시뮬레이션 결과"""
    my_hp_remaining: float        # HP 비율 0.0~1.0 (절대값 아님)
    enemy_hp_remaining: float     # HP 비율 0.0~1.0
    can_kill: bool                # enemy_hp_remaining <= 0
    i_survive: bool               # my_hp_remaining > 0
    verdict: str                  # GREEN/YELLOW/ORANGE/RED
    fight_duration: float         # 교전 지속 시간(초)
    wave_context: "WaveState | None" = field(default=None)


def simulate_full_fight(
    me: dict,
    enemy: dict,
    environment: dict,
    wave_state: "WaveState | None" = None,
) -> FightResult:
    """
    챔피언 스탯 + 환경 기반 교전 시뮬레이션.

    Args:
        me: {"hp": float, "max_hp": float, "ad": float, "armor": float, ...}
        enemy: 동일 구조
        environment: {"minion_count": int, "jungler_arrival_sec": float, ...}
        wave_state: WaveState (미니언 참전 여부 계산용)

    Returns:
        FightResult
    """
    # TODO: 챔피언별 스킬 콤보, 아이템 계산 구현
    result = simulate_full_fight_basic(me, enemy, environment)
    if wave_state is not None:
        result.wave_context = wave_state
    return result


def simulate_full_fight_basic(
    me: dict, enemy: dict, environment: dict
) -> FightResult:
    """
    기본 DPS 모델 교전 시뮬레이션 (스킬 미고려).

    me/enemy 필드: hp, max_hp, ad, ap, armor, mr, attack_speed
    """
    my_hp = me.get("hp", 1000.0)
    my_max_hp = me.get("max_hp", 1000.0)
    enemy_hp = enemy.get("hp", 1000.0)
    enemy_max_hp = enemy.get("max_hp", 1000.0)

    # 기본 딜량 계산
    my_dps = _calc_dps(me, enemy)
    enemy_dps = _calc_dps(enemy, me)

    if my_dps <= 0 and enemy_dps <= 0:
        return FightResult(
            my_hp_remaining=1.0, enemy_hp_remaining=1.0,
            can_kill=False, i_survive=True,
            verdict="YELLOW", fight_duration=0.0,
        )

    # 미니언 피해 추가
    minion_count = environment.get("minion_count", 0)
    fight_dur = _estimate_fight_duration(me, enemy)
    minion_dmg = calc_minion_damage(
        minion_count, fight_dur,
        me.get("armor", 50), "CASTER"
    )

    # 교전 결과 계산
    time_to_kill_enemy = enemy_hp / my_dps if my_dps > 0 else float("inf")
    time_to_kill_me = (my_hp - minion_dmg) / enemy_dps if enemy_dps > 0 else float("inf")

    # 남은 HP 비율
    my_hp_after = max(0.0, my_hp - enemy_dps * min(time_to_kill_enemy, fight_dur) - minion_dmg)
    enemy_hp_after = max(0.0, enemy_hp - my_dps * fight_dur)

    my_hp_ratio = my_hp_after / my_max_hp if my_max_hp > 0 else 0.0
    enemy_hp_ratio = enemy_hp_after / enemy_max_hp if enemy_max_hp > 0 else 0.0

    can_kill = enemy_hp_ratio <= 0
    i_survive = my_hp_ratio > 0
    verdict = _determine_verdict(my_hp_ratio, enemy_hp_ratio)

    return FightResult(
        my_hp_remaining=min(1.0, max(0.0, my_hp_ratio)),
        enemy_hp_remaining=min(1.0, max(0.0, enemy_hp_ratio)),
        can_kill=can_kill,
        i_survive=i_survive,
        verdict=verdict,
        fight_duration=fight_dur,
    )


def calc_minion_damage(
    enemy_minion_count: int,
    fight_duration_sec: float,
    defender_armor: float,
    minion_type: str = "CASTER",
) -> float:
    """
    미니언 피해 계산.

    Args:
        enemy_minion_count: 적 미니언 수
        fight_duration_sec: 교전 지속 시간(초)
        defender_armor: 방어력
        minion_type: "MELEE" | "CASTER" | "CANNON"
    """
    base_dps = {"MELEE": 12.0, "CASTER": 8.0, "CANNON": 35.0}.get(minion_type, 10.0)
    armor_reduction = 100.0 / (100.0 + max(0, defender_armor))
    return enemy_minion_count * base_dps * fight_duration_sec * armor_reduction


def _estimate_fight_duration(me: dict, enemy: dict) -> float:
    """교전 지속 시간 근사 (초)"""
    my_hp = me.get("hp", 1000.0)
    enemy_hp = enemy.get("hp", 1000.0)
    total_hp = my_hp + enemy_hp

    # DPS 합산으로 교전 시간 추정
    my_dps = _calc_dps(me, enemy)
    enemy_dps = _calc_dps(enemy, me)
    total_dps = my_dps + enemy_dps

    if total_dps <= 0:
        return 5.0

    return min(10.0, total_hp / total_dps)


def _calc_dps(attacker: dict, defender: dict) -> float:
    """단순 물리 DPS 계산"""
    ad = attacker.get("ad", 60.0)
    attack_speed = attacker.get("attack_speed", 0.6)
    armor = defender.get("armor", 50.0)
    armor_pen = attacker.get("armor_pen", 0.0)

    effective_armor = max(0.0, armor - armor_pen)
    armor_mult = 100.0 / (100.0 + effective_armor)

    return ad * attack_speed * armor_mult


def _calc_total_combo_damage(attacker: dict, defender: dict) -> float:
    """스킬 콤보 총 피해 추정 (stub)"""
    # TODO: 챔피언별 스킬 데이터 기반 계산
    base_dps = _calc_dps(attacker, defender)
    return base_dps * 3.0  # 3초 콤보 근사


def _determine_verdict(my_hp: float, enemy_hp: float) -> str:
    """
    HP 비율 기반 판정.
    GREEN: 압도적 승리, YELLOW: 유리, ORANGE: 불리, RED: 위험
    """
    if enemy_hp <= 0 and my_hp >= 0.5:
        return "GREEN"
    elif enemy_hp <= 0 and my_hp >= 0.2:
        return "YELLOW"
    elif enemy_hp <= 0:
        return "ORANGE"
    elif my_hp <= 0:
        return "RED"
    elif my_hp > enemy_hp + 0.3:
        return "GREEN"
    elif my_hp > enemy_hp:
        return "YELLOW"
    else:
        return "ORANGE"
