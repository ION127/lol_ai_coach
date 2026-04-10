"""add benchmark_stats, matchup_stats

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── benchmark_stats ────────────────────────────────────────────
    op.create_table(
        "benchmark_stats",
        sa.Column("champion_id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(20), primary_key=True),
        sa.Column("patch", sa.String(10), primary_key=True),
        sa.Column("region", sa.String(10), primary_key=True),
        sa.Column("avg_cs_per_min", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_vision_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_damage_dealt", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_ward_placed", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── matchup_stats ──────────────────────────────────────────────
    op.create_table(
        "matchup_stats",
        sa.Column("champion", sa.String(50), primary_key=True),
        sa.Column("opponent", sa.String(50), primary_key=True),
        sa.Column("role", sa.String(20), primary_key=True),
        sa.Column("patch", sa.String(10), primary_key=True),
        sa.Column("region", sa.String(10), primary_key=True),
        sa.Column("winrate", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("cs_diff_10", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gold_diff_15", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gold_timeline", sa.Text(), nullable=False, server_default="'[]'"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("matchup_stats")
    op.drop_table("benchmark_stats")
