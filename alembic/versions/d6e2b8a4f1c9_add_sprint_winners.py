"""add sprint_target_points + sprint_winners table

Backend for CRM task #7 ("Еженедельный спринт" winner lock-in): the
first user each week to reach a configurable points threshold is
frozen in as that week's winner.

- `leaderboard_points_settings.sprint_target_points` (nullable Integer)
  — admin-configurable threshold. NULL/0 means the feature is off: no
  winner-locking happens, existing points behavior is unchanged.
- `sprint_winners` — one row per week that had a winner. `week_start_at`
  (the Monday 00:00 Asia/Almaty that identifies the week, see
  `leaderboard_points.service.current_week_start_almaty`) is UNIQUE —
  that constraint IS the concurrency-safety mechanism: concurrent
  award paths race an `INSERT ... ON CONFLICT (week_start_at) DO
  NOTHING RETURNING user_id`, so only one row (and one winner) can
  ever exist per week regardless of how many requests hit the target
  at the same moment.

Revision ID: d6e2b8a4f1c9
Revises: c5d9f3b2a7e1
Create Date: 2026-07-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6e2b8a4f1c9"
down_revision: Union[str, None] = "c5d9f3b2a7e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_target_points", sa.Integer(), nullable=True),
    )

    bind = op.get_bind()
    if not sa.inspect(bind).has_table("sprint_winners"):
        op.create_table(
            "sprint_winners",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("week_start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("points_at_win", sa.Integer(), nullable=False),
            sa.Column(
                "won_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("week_start_at", name="uq_sprint_winners_week_start_at"),
        )


def downgrade() -> None:
    op.drop_table("sprint_winners")
    op.drop_column("leaderboard_points_settings", "sprint_target_points")
