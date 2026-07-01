"""add events table

Revision ID: 316e8e84c074
Revises: e1f2a3b4c5d6
Create Date: 2026-07-01 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "316e8e84c074"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("badge_text", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("prize_text", sa.String(100), nullable=True),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("secondary_text", sa.String(300), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("button_text", sa.String(100), nullable=True),
        sa.Column("bg_color", sa.String(20), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_max", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("events")
