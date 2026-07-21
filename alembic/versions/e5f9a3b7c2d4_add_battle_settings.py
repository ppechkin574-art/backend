"""add battle_settings (admin-editable battle tuning)

Single-row table for battle stars (win/draw/loss), format (questions per
subject, time) and bot difficulty — values that used to be hardcoded in
battle/service.py.

Revision ID: e5f9a3b7c2d4
Revises: d4e8f2a6b1c3
Create Date: 2026-07-21 01:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f9a3b7c2d4"
down_revision: Union[str, None] = "d4e8f2a6b1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "battle_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stars_win", sa.Integer(), server_default="50", nullable=False),
        sa.Column("stars_draw", sa.Integer(), server_default="25", nullable=False),
        sa.Column("stars_loss", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "questions_per_subject", sa.Integer(), server_default="5", nullable=False
        ),
        sa.Column("time_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column(
            "bot_win_rate_min", sa.Integer(), server_default="50", nullable=False
        ),
        sa.Column(
            "bot_win_rate_max", sa.Integer(), server_default="62", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("battle_settings")
