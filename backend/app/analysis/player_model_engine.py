"""
다경기 개인화 모델 업데이트 엔진.

EMA 기반 실수 패턴 누적 및 챌린저 대비 스탯 갭 업데이트.
Celery 동기 컨텍스트 → SyncSessionLocal 사용 (AsyncSession 금지).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# EMA 감쇠 계수 (0.1 = 최근 10경기 가중)
_EMA_ALPHA = 0.1
# 상위 집중 실수 개수
_TOP_FOCUS_TASKS = 3


class PlayerModelEngine:
    """
    다경기 PlayerModel 업데이트.

    Celery 워커에서 직접 호출:
    PlayerModelEngine().update_model(db, puuid, new_analysis)
    """

    def update_model(self, db, puuid: str, new_analysis: dict) -> dict:
        """
        PlayerModel EMA 업데이트.

        Args:
            db: SyncSession (psycopg2 기반)
            puuid: 플레이어 PUUID
            new_analysis: ctx.player_model["pending_update"]

        Returns:
            업데이트된 player_model dict
        """
        try:
            return self._update(db, puuid, new_analysis)
        except Exception:
            logger.exception("PlayerModelEngine.update_model 실패: puuid=%s", puuid)
            return {}

    def _update(self, db, puuid: str, new_analysis: dict) -> dict:
        """실제 업데이트 로직"""
        # TODO: SELECT ... FOR UPDATE 로 동시 업데이트 직렬화
        # from app.models import PlayerModel
        # model = db.query(PlayerModel).filter_by(puuid=puuid).with_for_update().first()

        # stub: 새 분석 데이터만 집계하여 반환
        mistakes = new_analysis.get("mistakes", [])
        stat_gaps = new_analysis.get("stat_gaps", {})

        mistake_patterns = _update_mistake_pattern({}, mistakes)
        updated_gaps = _update_stat_gaps({}, stat_gaps, _CHALLENGER_BENCHMARK)
        focus_tasks = _refresh_focus_tasks(mistake_patterns)

        return {
            "puuid": puuid,
            "mistake_patterns": mistake_patterns,
            "stat_gaps": updated_gaps,
            "focus_tasks": focus_tasks,
        }


# 챌린저 벤치마크 스탯 (근사값)
_CHALLENGER_BENCHMARK = {
    "gold_lead": 2000,    # 챌린저 평균 골드 리드
    "kill_lead": 3,       # 챌린저 평균 킬 리드
    "cs_per_min": 8.5,    # 챌린저 평균 분당 CS
    "vision_score": 1.5,  # 챌린저 평균 분당 시야 점수
}


def _update_mistake_pattern(
    existing: dict, mistakes: list[dict]
) -> dict:
    """
    EMA 기반 실수 패턴 빈도 누적.

    Args:
        existing: {mistake_type: frequency_ema}
        mistakes: [{"type": str, "timestamp_ms": int, "description": str}]

    Returns:
        업데이트된 패턴 dict
    """
    result = dict(existing)
    for mistake in mistakes:
        mtype = mistake.get("type", "unknown")
        current = result.get(mtype, 0.0)
        # EMA 업데이트: new = alpha * 1 + (1-alpha) * current
        result[mtype] = _EMA_ALPHA * 1.0 + (1 - _EMA_ALPHA) * current

    # 이번 경기에 없는 실수 타입은 감소
    for mtype in list(result.keys()):
        if not any(m.get("type") == mtype for m in mistakes):
            result[mtype] = (1 - _EMA_ALPHA) * result[mtype]

    return result


def _update_stat_gaps(
    existing: dict, stats: dict, benchmark: dict
) -> dict:
    """
    챌린저 대비 스탯 갭 EMA 업데이트.

    Args:
        existing: {stat_name: gap_ema}
        stats: 이번 경기 스탯
        benchmark: 챌린저 기준값
    """
    result = dict(existing)
    for stat, bench_val in benchmark.items():
        current_val = stats.get(stat, 0)
        gap = bench_val - current_val  # 양수 = 챌린저보다 부족

        existing_gap = result.get(stat, gap)
        # EMA 업데이트
        result[stat] = _EMA_ALPHA * gap + (1 - _EMA_ALPHA) * existing_gap

    return result


def _refresh_focus_tasks(mistake_patterns: dict) -> list[dict]:
    """
    상위 N개 실수 → FocusTask 갱신.

    Args:
        mistake_patterns: {mistake_type: frequency_ema}

    Returns:
        [{"type": str, "priority": int, "description": str}]
    """
    sorted_mistakes = sorted(
        mistake_patterns.items(), key=lambda x: x[1], reverse=True
    )[:_TOP_FOCUS_TASKS]

    return [
        {
            "type": mtype,
            "priority": idx + 1,
            "frequency": freq,
            "description": _mistake_description(mtype),
        }
        for idx, (mtype, freq) in enumerate(sorted_mistakes)
    ]


def _mistake_description(mistake_type: str) -> str:
    """실수 유형 설명"""
    return {
        "macro": "매크로 판단 개선 필요 (킬 후 오브젝트 우선순위)",
        "positioning": "포지셔닝 개선 필요 (갱 위험 지역 회피)",
        "wave": "웨이브 관리 개선 필요 (CS 손실 최소화)",
        "vision": "시야 관리 개선 필요 (와드 설치 타이밍)",
        "recall": "리콜 타이밍 개선 필요",
    }.get(mistake_type, f"{mistake_type} 개선 필요")
