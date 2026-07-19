"""add leaderboard_points_settings.reset_mode

Adds a "reset_mode" column ("interval" | "weekly_monday") so the
auto-reset schedule can be pinned to "every Monday 00:00 Asia/Almaty"
instead of only an arbitrary N-day interval — needed for the
"Еженедельный спринт" weekly reset (CRM task #6).

Revision ID: c5d9f3b2a7e1
Revises: c5d9f3a2b1e7
Create Date: 2026-07-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d9f3b2a7e1"
down_revision: Union[str, None] = "c5d9f3a2b1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column(
            "reset_mode", sa.String(20), nullable=False, server_default="interval"
        ),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_points_settings", "reset_mode")
