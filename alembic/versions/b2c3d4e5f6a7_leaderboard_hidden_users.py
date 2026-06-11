"""leaderboard_hidden_users table — admin hide-list for the leaderboard

Adds the `leaderboard_hidden_users` table. Each row marks one Keycloak
user as HIDDEN from the in-app leaderboard. The backend's
`UserPointsRepository.get_all_ranked` / `get_user_rank` filter these out
so hidden users vanish from the ranking and everyone below shifts up
(gap-free positions). Top-3 podium prizes are display-by-rank only, so
excluding a hidden user from the ranking also removes them from prizes.

`user_id` matches `user_points.user_id` EXACTLY (postgresql.UUID) so the
NOT IN / NOT EXISTS filter compares like-for-like with no casts.

No seed rows — the table starts empty (nobody hidden). The admin panel
populates it via POST /admin/leaderboard/hidden.

Revision ID: b2c3d4e5f6a7
Revises: a9b8c7d6e5f4
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leaderboard_hidden_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("leaderboard_hidden_users")
