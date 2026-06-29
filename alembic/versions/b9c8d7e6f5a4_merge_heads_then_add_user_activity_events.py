"""merge multiple heads and add user_activity_events table

Revision ID: b9c8d7e6f5a4
Revises: 2a5acb79a88d, a1f0e7e3b4c2, d3e4f5a6b7c8
Create Date: 2026-06-29 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = (
    "2a5acb79a88d",
    "a1f0e7e3b4c2",
    "d3e4f5a6b7c8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_activity_events",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(50), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_uae_user_time", "user_activity_events", ["user_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("idx_uae_user_time", table_name="user_activity_events")
    op.drop_table("user_activity_events")
