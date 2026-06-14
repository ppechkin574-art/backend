"""Add invitee_phone_hash to referral_redemptions for cross-account abuse prevention

sha256(phone) is stored on each redemption so the same phone number cannot
redeem a referral code twice — even after deleting and re-registering
(which produces a new Keycloak UUID but the same phone number).

A partial unique index (WHERE invitee_phone_hash IS NOT NULL) enforces this
at the DB level while still allowing NULL for rows created before this migration.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "referral_redemptions",
        sa.Column("invitee_phone_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uix_referral_redemptions_phone_hash",
        "referral_redemptions",
        ["invitee_phone_hash"],
        unique=True,
        postgresql_where=sa.text("invitee_phone_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uix_referral_redemptions_phone_hash",
        table_name="referral_redemptions",
    )
    op.drop_column("referral_redemptions", "invitee_phone_hash")
