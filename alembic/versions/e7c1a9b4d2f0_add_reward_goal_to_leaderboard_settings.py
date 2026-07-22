"""add reward-goal columns to leaderboard_points_settings

Backend for the home «До следующей награды» card (admin page «Турнир →
Награды за баллы»). Two columns on the existing singleton settings row:

- `reward_goal_enabled` (Boolean, default false) — master on/off toggle.
- `reward_goal_target_points` (nullable Integer) — the single points
  goal every user's total is measured against. NULL/0 == no active goal.

When disabled or target is NULL/0 the mobile client renders the card's
«Скоро новые цели» empty state instead of a progress bar. Read back by
`GET /leaderboard/me` (reward_enabled / reward_target_points).

Column adds are guarded by an inspector check so re-running against a DB
that already has them (partial/rerun deploy) is a no-op rather than an
error — same defensive stance as the sprint_winners migration's
`has_table` guard.

Revision ID: e7c1a9b4d2f0
Revises: d5b8f2a7c1e9
Create Date: 2026-07-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a9b4d2f0"
down_revision: Union[str, None] = "d5b8f2a7c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "leaderboard_points_settings"


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind)
    if "reward_goal_enabled" not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                "reward_goal_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )
    if "reward_goal_target_points" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("reward_goal_target_points", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind)
    if "reward_goal_target_points" in existing:
        op.drop_column(_TABLE, "reward_goal_target_points")
    if "reward_goal_enabled" in existing:
        op.drop_column(_TABLE, "reward_goal_enabled")
