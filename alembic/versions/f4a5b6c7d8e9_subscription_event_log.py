"""subscription_event_log: single audit trail for all subscription events

Append-only log across Apple/Google/admin — purchase, renewal, expiry,
refund, revoke, restore, verify-rejected, admin grant/reset — so support can
trace "я заплатил, где PRO?" from one place.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_event_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("user_id", sa.String, nullable=True),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("product_id", sa.String, nullable=True),
        sa.Column("transaction_id", sa.String, nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("environment", sa.String, nullable=True),
        sa.Column("detail", sa.String, nullable=True),
    )
    op.create_index(
        "ix_subscription_event_log_created_at",
        "subscription_event_log",
        ["created_at"],
    )
    op.create_index(
        "ix_subscription_event_log_user_id",
        "subscription_event_log",
        ["user_id"],
    )
    op.create_index(
        "ix_subscription_event_log_event_type",
        "subscription_event_log",
        ["event_type"],
    )
    op.create_index(
        "ix_subscription_event_log_transaction_id",
        "subscription_event_log",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_event_log_transaction_id",
        table_name="subscription_event_log",
    )
    op.drop_index(
        "ix_subscription_event_log_event_type",
        table_name="subscription_event_log",
    )
    op.drop_index(
        "ix_subscription_event_log_user_id",
        table_name="subscription_event_log",
    )
    op.drop_index(
        "ix_subscription_event_log_created_at",
        table_name="subscription_event_log",
    )
    op.drop_table("subscription_event_log")
