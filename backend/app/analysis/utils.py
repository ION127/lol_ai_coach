"""
분석 엔진 공통 순수 함수.

사이드이펙트 없음, DB 접근 없음.
모든 엔진이 이 모듈을 공통으로 사용한다.
"""
from __future__ import annotations

import bisect
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.analysis.wave_engine import WaveState

# 맵 중앙 좌표 (플레이어 위치를 찾지 못할 때 기본값)
_MAP_CENTER = {"x": 7500.0, "y": 7500.0}
_MAP_SIZE = 15000.0

# 미니언 공격력 (평균, 레인 단계별 다름)
_MINION_DPS = 12.0          # 근거리 미니언 DPS 근사값
_CANNON_DPS = 35.0          # 포탑 미니언 DPS 근사값
_RECALL_BASE_SEC = 8.0      # 기본 리콜 시간(초)
_CS_PER_WAVE = 6.0          # 웨이브당 CS 수 (근거리 3 + 원거리 3 근사)


# ── 스냅샷 조회 ──────────────────────────────────────────────────
def get_snapshot_at(timestamp_ms: int, snapshots: dict) -> dict:
    """
    이진탐색으로 O(log n) 가장 가까운 스냅샷 반환.

    Args:
        timestamp_ms: 조회할 타임스탬프 (ms)
        snapshots: {timestamp_ms: snap_dict}

    Returns:
        가장 가까운 타임스탬프의 스냅샷. 없으면 빈 dict.
    """
    if not snapshots:
        return {}

    keys = sorted(snapshots.keys())
    idx = bisect.bisect_left(keys, timestamp_ms)

    if idx == 0:
        return snapshots[keys[0]]
    if idx >= len(keys):
        return snapshots[keys[-1]]

    # 앞뒤 중 더 가까운 것 선택
    before = keys[idx - 1]
    after = keys[idx]
    if timestamp_ms - before <= after - timestamp_ms:
        return snapshots[before]
    return snapshots[after]


# ── 좌표 유틸 ────────────────────────────────────────────────────
def euclidean_distance(a: dict, b: dict) -> float:
    """{"x": float, "y": float} 두 점 간 유클리드 거리"""
    dx = a.get("x", 0) - b.get("x", 0)
    dy = a.get("y", 0) - b.get("y", 0)
    return math.sqrt(dx * dx + dy * dy)


def normalize_position(pos: dict) -> dict:
    """맵 좌표 (0~15000) → 정규화 (0.0~1.0)"""
    return {
        "x": max(0.0, min(1.0, pos.get("x", 0) / _MAP_SIZE)),
        "y": max(0.0, min(1.0, pos.get("y", 0) / _MAP_SIZE)),
    }


# ── 플레이어 조회 ────────────────────────────────────────────────
def _find_player(snap: dict, player_id: int) -> dict | None:
    """스냅샷에서 player_id로 플레이어 dict 조회"""
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            return p
    return None


def get_player_team(snap: dict, player_id: int) -> str:
    """snap['players']에서 player_id의 팀 반환. 없으면 "unknown"."""
    player = _find_player(snap, player_id)
    if player is None:
        return "unknown"
    return player.get("team", "unknown")


def get_player_position(snap: dict, player_id: int) -> dict:
    """
    snap['players']에서 player_id 위치 반환.
    없으면 맵 중앙 {"x":7500,"y":7500} 반환.
    """
    player = _find_player(snap, player_id)
    if player is None:
        return dict(_MAP_CENTER)
    return player.get("position", dict(_MAP_CENTER))


def get_player_stats(snap: dict, player_id: int) -> dict:
    """플레이어 전투 스탯 반환. 없으면 기본값 dict."""
    player = _find_player(snap, player_id)
    if player is None:
        return {"hp": 0, "max_hp": 1, "level": 1, "gold": 0, "cs": 0}
    return player


# ── 시야 유틸 ─────────────────────────────────────────────────────
def any_ward_covers(wards: list[dict], position: dict, radius: float = 900.0) -> bool:
    """
    wards 중 하나라도 position을 radius 내 커버하는지.

    Args:
        wards: [{"position": {"x": float, "y": float}, ...}]
        position: {"x": float, "y": float}
        radius: 시야 반경 (기본 900, 황초 기준)
    """
    for ward in wards:
        ward_pos = ward.get("position", {})
        if euclidean_distance(ward_pos, position) <= radius:
            return True
    return False


def any_ward_covers_path(
    wards: list[dict], path: list[dict], radius: float = 900.0
) -> bool:
    """
    경로(path) 상의 임의 지점이 와드 시야에 커버되는지.

    Args:
        path: [{"x": float, "y": float}, ...]
    """
    return any(any_ward_covers(wards, point, radius) for point in path)


# ── 웨이브 유틸 ──────────────────────────────────────────────────
def estimate_crash_time(my_minions: list, enemy_minions: list) -> float:
    """
    미니언 수/타입 기반 웨이브 충돌 예상 시간(초).
    단순 DPS 모델: 미니언 수 × DPS로 상대 미니언 처치 시간 계산.

    Returns:
        예상 충돌까지 남은 시간(초). 즉시 충돌이면 0.
    """
    if not my_minions or not enemy_minions:
        return 30.0  # 데이터 없으면 기본 30초

    my_count = len(my_minions)
    enemy_count = len(enemy_minions)

    # 포탑 미니언 수 계산 (type이 "CANNON" 또는 "SUPER")
    my_cannon = sum(1 for m in my_minions if m.get("type", "") in ("CANNON", "SUPER"))
    enemy_cannon = sum(1 for m in enemy_minions if m.get("type", "") in ("CANNON", "SUPER"))

    my_dps = (my_count - my_cannon) * _MINION_DPS + my_cannon * _CANNON_DPS
    enemy_dps = (enemy_count - enemy_cannon) * _MINION_DPS + enemy_cannon * _CANNON_DPS

    if my_dps <= 0 or enemy_dps <= 0:
        return 30.0

    # 상대 미니언 HP 근사 (공격력 × 처치 시간)
    # 단순화: 미니언 1마리 HP = 400
    enemy_total_hp = enemy_count * 400.0
    my_total_hp = my_count * 400.0

    time_to_kill_enemy = enemy_total_hp / my_dps
    time_to_kill_mine = my_total_hp / enemy_dps

    return max(0.0, min(time_to_kill_enemy, time_to_kill_mine))


def estimate_cs_loss_on_recall(wave_state: "WaveState", recall_duration_sec: float) -> int:
    """
    리콜 시 잃는 CS 추정치.

    wave_state.next_crash_estimate_sec 기준으로
    리콜 중 충돌하는 웨이브 수 × CS_PER_WAVE 계산.
    """
    total_time = recall_duration_sec + _RECALL_BASE_SEC  # 리콜 시간 + 복귀 시간
    time_until_crash = wave_state.next_crash_estimate_sec

    if time_until_crash > total_time:
        return 0  # 리콜 완료 전 충돌 없음

    # 충돌 이후 지나는 웨이브 수
    remaining_time = total_time - time_until_crash
    wave_interval_sec = 30.0  # 웨이브 주기 약 30초
    waves_missed = 1 + int(remaining_time / wave_interval_sec)

    cs_per_wave = int(_CS_PER_WAVE * (1 + wave_state.my_minion_count / 6))
    return waves_missed * cs_per_wave


# ── 이벤트 필터 유틸 ─────────────────────────────────────────────
def filter_events_in_window(
    events: list[dict],
    start_ms: int,
    end_ms: int,
    event_type: str | None = None,
) -> list[dict]:
    """
    특정 시간 구간 + 타입의 이벤트 필터링.

    Args:
        events: 전체 이벤트 목록
        start_ms: 시작 타임스탬프 (포함)
        end_ms: 종료 타임스탬프 (포함)
        event_type: None이면 타입 필터 없음
    """
    result = []
    for e in events:
        ts = e.get("timestamp", 0)
        if start_ms <= ts <= end_ms:
            if event_type is None or e.get("type") == event_type:
                result.append(e)
    return result


def get_events_for_player(
    events: list[dict], player_id: int, event_types: list[str] | None = None
) -> list[dict]:
    """특정 플레이어 관련 이벤트 필터링 (killerId, victimId, participantId 기준)"""
    result = []
    for e in events:
        data = e.get("data", e)
        is_relevant = (
            data.get("killerId") == player_id
            or data.get("victimId") == player_id
            or data.get("participantId") == player_id
            or data.get("creatorId") == player_id
        )
        if is_relevant:
            if event_types is None or e.get("type") in event_types:
                result.append(e)
    return result
