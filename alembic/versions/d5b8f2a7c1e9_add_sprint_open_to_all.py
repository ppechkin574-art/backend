"""add sprint_open_to_all flag (free-for-all sprint rubilnik)

When true, is_participant returns true for every user — the sprint is free/
open, the client shows «Начать тест» instead of «Купить доступ», and the
allowlist (sprint_participants) is bypassed but kept intact for later.

Revision ID: d5b8f2a7c1e9
Revises: f7a1c3e9d2b5
Create Date: 2026-07-21 08:42:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b8f2a7c1e9"
down_revision: Union[str, None] = "f7a1c3e9d2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column(
            "sprint_open_to_all",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_points_settings", "sprint_open_to_all")
