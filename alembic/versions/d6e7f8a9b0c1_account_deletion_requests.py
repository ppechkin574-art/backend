"""Add account_deletion_requests table for soft-delete grace period

Instead of instantly hard-deleting users from Keycloak, deletion is
scheduled DELETION_GRACE_DAYS (30) days in the future. The user can
cancel during this window. A background task in lifespan.py executes
the hard-delete once the scheduled_for timestamp has elapsed.

Benefits:
- Prevents instant delete → re-register loops that bypass per-account limits.
- Gives payment processors time to process chargebacks before the account vanishes.
- Lets the user cancel if they changed their mind.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_account_deletion_requests_user_id",
        "account_deletion_requests",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        "ix_account_deletion_requests_phone_hash",
        "account_deletion_requests",
        ["phone_hash"],
    )
    op.create_index(
        "ix_account_deletion_requests_scheduled_for",
        "account_deletion_requests",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_deletion_requests_scheduled_for",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_phone_hash",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_user_id",
        table_name="account_deletion_requests",
    )
    op.drop_table("account_deletion_requests")
