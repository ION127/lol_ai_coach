"""initial schema — users, analysis_records

Revision ID: 0001
Revises:
Create Date: 2026-04-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("refresh_token", sa.String(128), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── analysis_records ──────────────────────────────────────────
    op.create_table(
        "analysis_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("data_quality", sa.String(10), nullable=True),
        sa.Column("s3_key", sa.String(512), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("layer1_json", sa.Text(), nullable=True),
        sa.Column("layer2_json", sa.Text(), nullable=True),
        sa.Column("layer3_json", sa.Text(), nullable=True),
        sa.Column("layer4_json", sa.Text(), nullable=True),
        sa.Column("script_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_analysis_records_user_id", "analysis_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_records_user_id")
    op.drop_table("analysis_records")
    op.drop_index("ix_users_email")
    op.drop_table("users")
