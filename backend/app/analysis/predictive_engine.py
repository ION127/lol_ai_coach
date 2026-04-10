"""
미래 예측 엔진.

갱 위험, 킬각 창, 오브젝트 창을 예측한다.
"""
from __future__ import annotations

import logging

from app.analysis.utils import (
    euclidean_distance,
    get_player_position,
    get_snapshot_at,
)

logger = logging.getLogger(__name__)

# 정글러 이동 속도 테이블 (ms per 1000 units)
JUNGLER_SPEED_MAP: dict[str, float] = {
    "default": 340.0,   # 기본 이동 속도
    "fast": 380.0,      # 이동기 보유 정글러
}

# 갱 위험 반경
_GANK_DANGER_RADIUS = 3000.0
_SCAN_INTERVAL_MS = 30_000   # 30초마다 예측

# 오브젝트 타이머
_BARON_SPAWN_MS = 20 * 60 * 1000
_DRAGON_RESPAWN_MS = 5 * 60 * 1000


class PredictiveEngine:
    """
    GameContext → predictive_warnings 생성.

    인터페이스: run(ctx) -> {"predictive_warnings": list}
    """

    def run(self, ctx) -> dict:
        try:
            warnings = self._analyze(ctx)
            return {"predictive_warnings": warnings}
        except Exception:
            logger.exception("PredictiveEngine 실패")
            return {"predictive_warnings": []}

    def _analyze(self, ctx) -> list[dict]:
        """타임라인 스캔하여 위험 예측"""
        warnings = []
        duration_ms = ctx.game_duration_ms()

        ts = _SCAN_INTERVAL_MS
        while ts <= duration_ms:
            if ctx.has_snapshots():
                snap = get_snapshot_at(ts, ctx.snapshots)
                player_pos = get_player_position(snap, ctx.player_id)

                # 갱 위험 예측
                gank_warning = _predict_gank_risk(ts, snap, ctx.snapshots, ctx.player_id)
                if gank_warning:
                    warnings.append(gank_warning)

                # 킬각 예측
                kill_window = _predict_kill_window(ts, snap, ctx.snapshots, ctx.player_id)
                if kill_window:
                    warnings.append(kill_window)

            # 오브젝트 창 예측 (스냅샷 불필요)
            obj_window = _predict_objective_window(ts, ctx.snapshots if ctx.has_snapshots() else {})
            if obj_window:
                warnings.append(obj_window)

            ts += _SCAN_INTERVAL_MS

        return warnings


def _predict_gank_risk(
    ts_ms: int, snap: dict, snapshots: dict, player_id: int
) -> dict | None:
    """
    갱 위험 예측.

    정글러 위치 추정 → 플레이어 도달 시간 계산.
    """
    player_pos = get_player_position(snap, player_id)
    player_team = "blue"
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            player_team = p.get("team", "blue")
            break

    # 적 정글러 위치 추정 (role="JUNGLE"인 플레이어)
    enemy_jungler = None
    for p in snap.get("players", []):
        if p.get("team") != player_team and p.get("role") == "JUNGLE":
            enemy_jungler = p
            break

    if enemy_jungler is None:
        return None

    jungler_pos = enemy_jungler.get("position", {"x": 7500, "y": 7500})
    dist = euclidean_distance(player_pos, jungler_pos)

    # 도달 시간 계산
    speed = JUNGLER_SPEED_MAP["default"]
    arrival_sec = dist / speed

    if arrival_sec > 8.0:
        return None  # 8초 이상 거리 → 위험 없음

    severity = "CRITICAL" if arrival_sec < 3.0 else "HIGH" if arrival_sec < 5.0 else "MEDIUM"

    return {
        "timestamp_ms": ts_ms,
        "type": "GANK_RISK",
        "severity": severity,
        "description": f"적 정글러 {arrival_sec:.1f}초 내 도달 위험",
        "details": {"arrival_sec": arrival_sec, "distance": dist},
    }


def _predict_kill_window(
    ts_ms: int, snap: dict, snapshots: dict, player_id: int
) -> dict | None:
    """
    킬각 창 예측.

    적 HP가 낮을 때 킬 가능 시간대 예측.
    """
    player_team = "blue"
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            player_team = p.get("team", "blue")
            break

    # 근처 낮은 HP 적 탐색
    player_pos = get_player_position(snap, player_id)
    for p in snap.get("players", []):
        if p.get("team") == player_team:
            continue

        enemy_pos = p.get("position", {"x": 7500, "y": 7500})
        dist = euclidean_distance(player_pos, enemy_pos)

        if dist > 2000:
            continue  # 너무 멀면 스킵

        hp = p.get("hp", 1.0)
        max_hp = p.get("max_hp", 1.0)
        hp_ratio = hp / max_hp if max_hp > 0 else 1.0

        if hp_ratio < 0.3:
            return {
                "timestamp_ms": ts_ms,
                "type": "KILL_WINDOW",
                "severity": "HIGH",
                "description": f"근처 적 HP {hp_ratio:.0%} — 킬각 존재",
                "details": {"enemy_id": p.get("id"), "hp_ratio": hp_ratio},
            }

    return None


def _predict_objective_window(ts_ms: int, snapshots: dict) -> dict | None:
    """
    오브젝트 창 예측.

    바론/드래곤 스폰 타이밍 근접 시 알림.
    """
    # 바론: 20분 이후
    if ts_ms >= _BARON_SPAWN_MS:
        time_to_check = ts_ms % (5 * 60 * 1000)  # 5분 주기
        if time_to_check < _SCAN_INTERVAL_MS:
            return {
                "timestamp_ms": ts_ms,
                "type": "OBJECTIVE_WINDOW",
                "severity": "MEDIUM",
                "description": "바론 나스호르 스폰 시간 — 시야 확보 필요",
                "details": {"objective": "BARON"},
            }

    return None
