"""trial_history table for phone-hash trial-grant tracking

Holds a one-row-per-phone audit trail of free trials granted, keyed by
sha256(phone) so the actual number doesn't sit in the DB unhashed.
Survives Keycloak user deletion — so an attacker can't (a) register
+77001234567 → activate trial → admin deletes the user → register
again on the same number → free trial again.

The existing `used_trial` attribute on the Keycloak user record stays
as the primary check (it's per-user and covers all flows including
Apple IAP introductory offer). This table is a secondary phone-level
gate that closes the delete-and-recreate loophole.

Revision ID: e5a2b8d3c7f1
Revises: d4f1e2a3b5c6
Create Date: 2026-05-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5a2b8d3c7f1"
down_revision: Union[str, Sequence[str], None] = "d4f1e2a3b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trial_history",
        sa.Column("phone_hash", sa.String(64), primary_key=True),
        sa.Column(
            "first_granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("trial_history")
