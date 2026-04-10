"""
플레이어 의도 추론 엔진.

동선 + 스킬 + 이벤트로 플레이어 의도를 추론한다.
FALLBACK 모드: 위치 데이터 없을 때 이벤트만으로 추론.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.analysis.utils import (
    euclidean_distance,
    get_player_position,
    get_snapshot_at,
)

logger = logging.getLogger(__name__)

# 의도 분류
_INTENTS = ("KILL_ATTEMPT", "ROAM", "FARM", "RECALL", "UNCLEAR")
_SCAN_INTERVAL_MS = 10_000  # 10초마다 의도 분석

# 위치 기반 의도 판단 기준
_ROAM_DISTANCE = 5000.0      # 5000 유닛 이상 이동 → ROAM
_FARM_CS_GAIN = 3            # CS 3 이상 증가 → FARM
_KILL_PROXIMITY = 2000.0     # 적과 2000 유닛 이내 → KILL_ATTEMPT 후보


@dataclass
class PlayerIntent:
    """특정 시점의 플레이어 의도"""
    intent: str                # KILL_ATTEMPT/ROAM/FARM/RECALL/UNCLEAR
    evaluation: str            # CORRECT/WRONG_INTENT/WRONG_EXECUTION/BOTH_WRONG
    confidence: float          # 0.0~1.0
    description: str           # 설명 텍스트


class IntentEngine:
    """
    GameContext → intent_map 생성.

    인터페이스: run(ctx) -> {"intent_map": {ts: PlayerIntent}}
    """

    def run(self, ctx) -> dict:
        try:
            intent_map = self._analyze(ctx)
            return {"intent_map": intent_map}
        except Exception:
            logger.exception("IntentEngine 실패")
            return {"intent_map": {}}

    def _analyze(self, ctx) -> dict[int, PlayerIntent]:
        """타임라인 스캔하여 의도 추론"""
        intent_map: dict[int, PlayerIntent] = {}
        duration_ms = ctx.game_duration_ms()

        ts = _SCAN_INTERVAL_MS
        prev_snap = None

        while ts <= duration_ms:
            if ctx.has_snapshots():
                snap = get_snapshot_at(ts, ctx.snapshots)
                intent = self._infer_intent(ts, snap, prev_snap, ctx)
                intent_map[ts] = intent
                prev_snap = snap
            else:
                # FALLBACK: 이벤트만으로 추론
                intent = self._infer_from_events(ts, ctx)
                if intent:
                    intent_map[ts] = intent

            ts += _SCAN_INTERVAL_MS

        return intent_map

    def _infer_intent(
        self, ts: int, snap: dict, prev_snap: dict | None, ctx
    ) -> PlayerIntent:
        """스냅샷 기반 의도 추론"""
        player_pos = get_player_position(snap, ctx.player_id)

        # CS 변화
        cs_gain = 0
        if prev_snap:
            prev_cs = _get_player_stat(prev_snap, ctx.player_id, "cs")
            curr_cs = _get_player_stat(snap, ctx.player_id, "cs")
            cs_gain = curr_cs - prev_cs

        # 이동 거리
        movement = 0.0
        if prev_snap:
            prev_pos = get_player_position(prev_snap, ctx.player_id)
            movement = euclidean_distance(player_pos, prev_pos)

        # 적과의 거리
        player_team = "blue"
        for p in snap.get("players", []):
            if p.get("id") == ctx.player_id:
                player_team = p.get("team", "blue")
                break

        nearest_enemy_dist = float("inf")
        for p in snap.get("players", []):
            if p.get("team") != player_team:
                enemy_pos = p.get("position", {"x": 7500, "y": 7500})
                dist = euclidean_distance(player_pos, enemy_pos)
                nearest_enemy_dist = min(nearest_enemy_dist, dist)

        # 의도 분류
        intent = _classify_intent(cs_gain, movement, nearest_enemy_dist)
        evaluation = self._evaluate_intent(ts, intent, ctx)
        confidence = 0.7 if ctx.has_snapshots() else 0.3

        return PlayerIntent(
            intent=intent,
            evaluation=evaluation,
            confidence=confidence,
            description=_intent_description(intent, cs_gain, movement),
        )

    def _infer_from_events(self, ts: int, ctx) -> PlayerIntent | None:
        """이벤트 기반 의도 추론 (FALLBACK)"""
        from app.analysis.utils import filter_events_in_window
        window = filter_events_in_window(ctx.events, ts - _SCAN_INTERVAL_MS, ts)

        player_events = [
            e for e in window
            if (e.get("data", e).get("participantId") == ctx.player_id
                or e.get("data", e).get("killerId") == ctx.player_id)
        ]

        if not player_events:
            return None

        for e in player_events:
            etype = e.get("type", "")
            if etype == "CHAMPION_KILL":
                return PlayerIntent(
                    intent="KILL_ATTEMPT",
                    evaluation="CORRECT",
                    confidence=0.5,
                    description="킬 이벤트 감지",
                )
            elif etype == "RECALL":
                return PlayerIntent(
                    intent="RECALL",
                    evaluation="CORRECT",
                    confidence=0.8,
                    description="리콜 이벤트 감지",
                )

        return PlayerIntent(
            intent="UNCLEAR",
            evaluation="CORRECT",
            confidence=0.2,
            description="이벤트 기반 추론 불가",
        )

    def _evaluate_intent(self, ts: int, intent: str, ctx) -> str:
        """의도 적절성 평가"""
        # 게임 국면과 의도 매칭 확인
        if not ctx.game_state_timeline:
            return "CORRECT"

        nearest_state = min(
            ctx.game_state_timeline,
            key=lambda s: abs(s.timestamp_ms - ts),
            default=None,
        )
        if nearest_state is None:
            return "CORRECT"

        phase = nearest_state.phase

        # 앞서고 있을 때 FARM → WRONG_INTENT (오브젝트 처리해야)
        if phase in ("AHEAD", "SNOWBALL") and intent == "FARM":
            return "WRONG_INTENT"

        # 뒤처질 때 KILL_ATTEMPT → WRONG_INTENT (위험)
        if phase in ("BEHIND", "COMEBACK") and intent == "KILL_ATTEMPT":
            return "WRONG_INTENT"

        return "CORRECT"


def _classify_intent(
    cs_gain: int, movement: float, nearest_enemy_dist: float
) -> str:
    """의도 분류"""
    if nearest_enemy_dist < _KILL_PROXIMITY:
        return "KILL_ATTEMPT"
    if movement > _ROAM_DISTANCE:
        return "ROAM"
    if cs_gain >= _FARM_CS_GAIN:
        return "FARM"
    return "UNCLEAR"


def _get_player_stat(snap: dict, player_id: int, stat: str) -> int:
    """스냅샷에서 특정 스탯 반환"""
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            return int(p.get(stat, 0))
    return 0


def _intent_description(intent: str, cs_gain: int, movement: float) -> str:
    """의도 설명 텍스트"""
    return {
        "KILL_ATTEMPT": f"적 근접 — 교전 시도 (이동: {movement:.0f})",
        "ROAM": f"대규모 이동 감지 ({movement:.0f} 유닛) — 로밍",
        "FARM": f"CS {cs_gain}개 획득 — 파밍",
        "RECALL": "리콜 중",
        "UNCLEAR": "명확한 의도 없음",
    }.get(intent, "")
