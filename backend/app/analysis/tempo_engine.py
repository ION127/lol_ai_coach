"""
템포/리콜 분석 엔진.

리콜 시점 평가 및 파워 스파이크 타이밍 분석.
"""
from __future__ import annotations

import logging

from app.analysis.utils import filter_events_in_window, get_snapshot_at

logger = logging.getLogger(__name__)

# 리콜 평가 기준 (ms)
_RECALL_EVENT_TYPE = "ITEM_PURCHASED"
_BASE_RECALL_MS = 8_000         # 기본 리콜 8초
_SCAN_INTERVAL_MS = 10_000      # 10초마다 리콜 평가


class TempoEngine:
    """
    GameContext → recall_evals, power_spikes 생성.

    인터페이스: run(ctx) -> {"recall_evals": list, "power_spikes": list}
    """

    def run(self, ctx) -> dict:
        try:
            recall_evals = self._analyze_recalls(ctx)
            power_spikes = self._find_power_spikes(ctx)
            return {"recall_evals": recall_evals, "power_spikes": power_spikes}
        except Exception:
            logger.exception("TempoEngine 실패")
            return {"recall_evals": [], "power_spikes": []}

    def _analyze_recalls(self, ctx) -> list[dict]:
        """리콜 이벤트 감지 후 타이밍 평가"""
        recall_events = [
            e for e in ctx.events
            if e.get("type") == "RECALL"
            and e.get("data", e).get("participantId") == ctx.player_id
        ]

        evals = []
        for event in recall_events:
            ts = event.get("timestamp", 0)
            rating = self._rate_recall(ts, ctx)
            evals.append({
                "timestamp_ms": ts,
                "rating": rating,
                "reason": _recall_reason(rating),
            })

        return evals

    def _rate_recall(self, ts: int, ctx) -> str:
        """
        리콜 타이밍 평가.
        OPTIMAL / GOOD / WASTEFUL / DANGEROUS
        """
        if not ctx.has_snapshots():
            return "GOOD"  # 데이터 없으면 중립

        snap = get_snapshot_at(ts, ctx.snapshots)

        # 플레이어 HP 확인
        hp_ratio = _get_hp_ratio(snap, ctx.player_id)

        # 직전 5초 내 교전 확인
        recent_fights = filter_events_in_window(
            ctx.events, ts - 5_000, ts, event_type="CHAMPION_KILL"
        )

        # 웨이브 상태 (wave_timeline이 채워진 경우)
        cs_loss = 0
        if ctx.wave_timeline:
            wave_ts = min(ctx.wave_timeline.keys(), key=lambda k: abs(k - ts))
            wave_state = ctx.wave_timeline.get(wave_ts)
            if wave_state:
                cs_loss = wave_state.cs_loss_if_recalled_now

        # 평가 로직
        if hp_ratio < 0.2:
            return "OPTIMAL"   # 낮은 HP → 리콜 필요
        if recent_fights:
            return "DANGEROUS"  # 교전 직후 리콜 위험
        if cs_loss > 12:
            return "WASTEFUL"  # 많은 CS 손실
        if hp_ratio < 0.5 or cs_loss <= 6:
            return "GOOD"
        return "WASTEFUL"

    def _find_power_spikes(self, ctx) -> list[dict]:
        """아이템 완성 시점 파워 스파이크 감지"""
        item_events = [
            e for e in ctx.events
            if e.get("type") == "ITEM_PURCHASED"
            and e.get("data", e).get("participantId") == ctx.player_id
        ]

        spikes = []
        for event in item_events:
            ts = event.get("timestamp", 0)
            data = event.get("data", event)
            item_id = data.get("itemId", 0)

            # 주요 완성 아이템 감지 (item_id > 3000 = 완성 아이템 근사)
            if item_id > 3000:
                spikes.append({
                    "timestamp_ms": ts,
                    "item_id": item_id,
                    "spike_level": "MAJOR",
                })

        return spikes


def _get_hp_ratio(snap: dict, player_id: int) -> float:
    """스냅샷에서 HP 비율 반환"""
    for p in snap.get("players", []):
        if p.get("id") == player_id:
            hp = p.get("hp", 1.0)
            max_hp = p.get("max_hp", 1.0)
            return hp / max_hp if max_hp > 0 else 1.0
    return 1.0


def _recall_reason(rating: str) -> str:
    """리콜 평가 사유 텍스트"""
    return {
        "OPTIMAL": "HP 부족으로 리콜 필요",
        "GOOD": "적절한 리콜 타이밍",
        "WASTEFUL": "CS 손실이 발생하는 비효율적 리콜",
        "DANGEROUS": "교전 직후 위험한 리콜",
    }.get(rating, "")
