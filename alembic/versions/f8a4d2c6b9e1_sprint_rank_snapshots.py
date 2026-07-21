"""weekly sprint: daily rank snapshots for the up/down movement badge

CRM #19 — the weekly-standings screen shows a "moved up/down N places"
badge next to each participant. Movement is measured against the start of
the current day: a background job writes one snapshot row per participant
per day (~00:00 Asia/Almaty), and the standings query diffs today's live
rank against the latest snapshot.

`(week_start_at, captured_for_day, user_id)` is unique so a job re-run in
the same day updates nothing rather than duplicating.

Revision ID: f8a4d2c6b9e1
Revises: e7f3c9d1a2b4
Create Date: 2026-07-20 22:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a4d2c6b9e1"
down_revision: Union[str, None] = "e7f3c9d1a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("sprint_rank_snapshots"):
        return
    op.create_table(
        "sprint_rank_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("week_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_for_day", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "week_start_at",
            "captured_for_day",
            "user_id",
            name="uq_sprint_rank_snapshot",
        ),
    )
    op.create_index(
        "ix_sprint_rank_snapshots_week",
        "sprint_rank_snapshots",
        ["week_start_at", "captured_for_day"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sprint_rank_snapshots_week", table_name="sprint_rank_snapshots"
    )
    op.drop_table("sprint_rank_snapshots")
