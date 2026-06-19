"""apple_notifications: raw store + dedup for App Store Server Notifications V2

One row per notificationUUID (UNIQUE primary key) so Apple's at-least-once
delivery is deduped atomically; the raw signed JWS is kept for audit / replay.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-06-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "apple_notifications",
        sa.Column("notification_uuid", sa.String(64), primary_key=True),
        sa.Column("notification_type", sa.String(64), nullable=True),
        sa.Column("raw", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_apple_notifications_created_at",
        "apple_notifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_apple_notifications_created_at", table_name="apple_notifications"
    )
    op.drop_table("apple_notifications")
