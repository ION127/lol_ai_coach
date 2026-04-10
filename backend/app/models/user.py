from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    """
    서비스 계정 ORM.

    설계 결정:
    - Riot 계정(puuid) 연동은 선택 사항 → 별도 테이블로 분리 가능
    - refresh_token: 단일 기기 지원. 다중 기기 필요 시 UserSession 테이블 분리
    - hashed_password: bcrypt 60자이나 여유 확보를 위해 128자 컬럼
    """

    __tablename__ = "users"

    # ── PK ────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, comment="UUID v4"
    )

    # ── 기본 정보 ─────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ── 시간 ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Refresh Token (DB 저장 → 탈취 시 서버에서 즉시 폐기) ──────
    # opaque UUID 문자열 (JWT 아님)
    refresh_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, default=None
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} active={self.is_active}>"
