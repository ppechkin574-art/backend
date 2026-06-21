"""google_notifications: raw store + dedup for Google Play RTDN

One row per Pub/Sub messageId (UNIQUE primary key) so Google's at-least-once
delivery is deduped atomically; the raw Pub/Sub envelope is kept for audit /
replay. Mirrors apple_notifications.

Revision ID: 9a8b7c6d5e4f
Revises: c7d8e9f0a1b2
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9a8b7c6d5e4f"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "google_notifications",
        sa.Column("message_id", sa.String(128), primary_key=True),
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
        "ix_google_notifications_created_at",
        "google_notifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_google_notifications_created_at", table_name="google_notifications"
    )
    op.drop_table("google_notifications")
