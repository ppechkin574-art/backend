"""add user_activity_events table

Revision ID: a1b2c3d4e5f6
Revises: fc858cd71edc
Create Date: 2026-06-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fc858cd71edc"
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
