"""Add invitee_rewarded_at to referral_redemptions

Deferred-reward policy (13.06.2026): the invitee's stars/days are NOT
granted on code redemption — they are held until the invitee makes
their FIRST real paid subscription (trial does not count).

NULL   → reward still pending (all rows created after this migration)
NOT NULL → reward already granted at that timestamp

Existing rows were granted immediately under the old instant policy,
so the migration back-fills them with redeemed_at so they are treated
as already rewarded.

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f6
Create Date: 2026-06-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "referral_redemptions",
        sa.Column("invitee_rewarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Mark all pre-migration rows as already rewarded (instant policy was in effect).
    op.execute(
        """
        UPDATE referral_redemptions
        SET invitee_rewarded_at = redeemed_at
        WHERE invitee_rewarded_at IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_column("referral_redemptions", "invitee_rewarded_at")
