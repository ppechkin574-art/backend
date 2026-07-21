"""weekly sprint: points-per-correct-answer for the sprint test

CRM #19 — the sprint test credits points answer-by-answer (unlike a normal
ЕНТ test, one score at the end). This column is how many points a correct
answer is worth; the admin sets it in «Турнир → Спринт». NULL/0 disables
answer scoring.

Revision ID: b2c6f0d4e8a3
Revises: a1b5e9c3d7f2
Create Date: 2026-07-21 00:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c6f0d4e8a3"
down_revision: Union[str, None] = "a1b5e9c3d7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_points_per_answer", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_points_settings", "sprint_points_per_answer")
