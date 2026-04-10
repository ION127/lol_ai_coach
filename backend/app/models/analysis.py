from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalysisRecord(Base):
    """
    .rofl 분석 작업 레코드 ORM.

    status 전이:
        "pending" → "processing" → "complete"
                                 ↘ "failed"

    layer1_json ~ script_json: 분석 완료 후 채워짐 (nullable)
    metadata_json: Celery 워커에 전달할 분석 파라미터
        {champion_id, player_id, puuid, role, opponent, match_id, region, patch}
    s3_key: .rofl 파일 S3 경로 → 분석 완료 즉시 삭제 (Riot Policy §7)
    data_quality: "FULL" | "PARTIAL" | "FALLBACK"
    """

    __tablename__ = "analysis_records"

    # ── PK ────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, comment="UUID v4"
    )

    # ── 소유자 ────────────────────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── 상태 ──────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    data_quality: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None,
        comment="FULL | PARTIAL | FALLBACK"
    )

    # ── 파일/파라미터 ─────────────────────────────────────────────
    s3_key: Mapped[str | None] = mapped_column(
        String(512), nullable=True, default=None
    )
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment="JSON: champion_id, player_id, puuid, role, opponent, match_id"
    )

    # ── 분석 결과 레이어 ───────────────────────────────────────────
    layer1_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    layer2_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    layer3_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    layer4_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    script_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment="코칭 스크립트 JSON"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )

    # ── 시간 ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisRecord id={self.id!r} user={self.user_id!r} "
            f"status={self.status!r} quality={self.data_quality!r}>"
        )
