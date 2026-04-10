from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlayerModel(Base):
    """
    다경기 플레이어 약점 모델 ORM.

    puuid (PK): Riot PUUID — 소환사 이름 변경에도 불변 (78자)

    JSON 컬럼 스키마
    ─────────────────────────────────────────────────────────────
    recurring_mistakes: list[dict]
        {
            "mistake_type": str,    # "wave_fight_while_behind" 등
            "frequency": float,     # 경기당 평균 발생 횟수 (EMA)
            "severity": str,        # "high" | "medium" | "low"
            "trend": str,           # "improving" | "stable" | "worsening"
            "first_seen": str,      # ISO datetime 문자열
            "last_seen": str,
            "game_count": int
        }

    current_focus: list[dict]  (최대 3개)
        {
            "title": str,
            "description": str,
            "metric": str,          # 측정 지표명
            "target": float,        # 목표 수치
            "current": float,       # 현재 수치
            "progress": float,      # 0.0~1.0
            "deadline_games": int
        }

    growth_history: list[dict]  (경기당 1 스냅샷)
        {
            "recorded_at": str,
            "games_analyzed": int,
            "cs_per_min": float,
            "vision_score": float,
            "wave_behind_fight_rate": float,
            "optimal_recall_rate": float,
            "kda": float,
            "overall_score": float  # 0.0~1.0
        }

    stat_gaps: dict
        {"cs_per_min": float, "vision_score": float, ...}  # 챌린저 대비 차이

    strengths: list[str]  # 챌린저 대비 우수한 지표 이름 목록

    동시 업데이트 보호:
    - PlayerModelEngine.update_model()에서 SELECT ... FOR UPDATE 사용
    - JSON 컬럼 in-place 수정 후 반드시 새 객체 재할당 필요
      (SQLAlchemy가 JSON 내부 변경을 감지하지 못함)
      예: model.recurring_mistakes = list(model.recurring_mistakes)
    """

    __tablename__ = "player_models"

    # ── PK ────────────────────────────────────────────────────────
    puuid: Mapped[str] = mapped_column(
        String(78), primary_key=True,
        comment="Riot PUUID (78자 고정)"
    )

    # ── 시간 ──────────────────────────────────────────────────────
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── JSON 컬럼 ─────────────────────────────────────────────────
    # default=list / dict 는 callable → 행마다 새 객체 생성 (공유 안 됨)
    recurring_mistakes: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    stat_gaps: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    strengths: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    current_focus: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    growth_history: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    def __repr__(self) -> str:
        return (
            f"<PlayerModel puuid={self.puuid[:8]!r}... "
            f"mistakes={len(self.recurring_mistakes)} "
            f"focus={len(self.current_focus)}>"
        )
