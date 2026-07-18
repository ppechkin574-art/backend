"""add leaderboard_points_settings table

Revision ID: b4c8e2a1f6d3
Revises: a3f7c1b9d2e4
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c8e2a1f6d3"
down_revision: Union[str, None] = "a3f7c1b9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leaderboard_points_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "auto_reset_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("leaderboard_points_settings")
