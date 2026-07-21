"""add admin-defined sprint dates to leaderboard_points_settings

The weekly sprint gains an explicit, admin-chosen period: sprint_start_at /
sprint_end_at (arbitrary date range). When both are set the sprint runs
[start, end); NULL/NULL keeps the legacy implicit Mon–Sun week.

Revision ID: d4e8f2a6b1c3
Revises: c3d7e1f5a9b2
Create Date: 2026-07-21 01:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8f2a6b1c3"
down_revision: Union[str, None] = "c3d7e1f5a9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_end_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_points_settings", "sprint_end_at")
    op.drop_column("leaderboard_points_settings", "sprint_start_at")
