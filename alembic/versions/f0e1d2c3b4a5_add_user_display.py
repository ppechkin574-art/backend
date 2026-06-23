"""Add user_display table — denormalized leaderboard name/avatar snapshot.

Lets the leaderboard read display names/avatars from Postgres instead of one
Keycloak Admin-API call per user. Additive (new table only) — safe to deploy.

Revision ID: f0e1d2c3b4a5
Revises: d1e2f3a4b5c6
Create Date: 2026-06-23
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_display",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_display")
