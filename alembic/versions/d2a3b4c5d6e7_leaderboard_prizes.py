"""Leaderboard prizes table + 3 seed rows for top-1/2/3

Adds the `leaderboard_prizes` table powering the «top-3 receives»
modal on the iOS leaderboard screen. Operator edits these via the
new admin panel section.

Seeds three default rows so the iOS client has something to render
on first launch — operator can edit/disable from the admin UI.

Revision ID: d2a3b4c5d6e7
Revises: c2f3a4b5c6d7
Create Date: 2026-05-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2a3b4c5d6e7"
down_revision: Union[str, None] = "c2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leaderboard_prizes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("icon_key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "description",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("rank", name="uq_leaderboard_prizes_rank"),
    )

    # Default prizes for top-1/2/3 so the iOS client has something to
    # render the first time the leaderboard screen loads. Operator
    # tweaks from the admin panel.
    op.execute(
        """
        INSERT INTO leaderboard_prizes (rank, icon_key, title, description, is_active)
        VALUES
          (1, 'trophy',       '1 место', 'Главный приз: настраивается оператором.', true),
          (2, 'medal_silver', '2 место', 'Серебряный приз: настраивается оператором.', true),
          (3, 'medal_bronze', '3 место', 'Бронзовый приз: настраивается оператором.', true)
        ON CONFLICT (rank) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("leaderboard_prizes")
