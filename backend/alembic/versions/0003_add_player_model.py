"""add player_models

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_models",
        sa.Column("puuid", sa.String(78), primary_key=True, comment="Riot PUUID 78자"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "recurring_mistakes",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "stat_gaps",
            postgresql.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "strengths",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "current_focus",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "growth_history",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_table("player_models")
