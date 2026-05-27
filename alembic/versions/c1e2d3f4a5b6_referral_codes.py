"""Referral code feature — codes table, redemptions table, policy seeds

Adds two tables for the user-to-user invitation feature requested
by operator 27.05.2026:

  - `referral_codes`        one personal code per user, lazily minted
                            on first GET /user/referral/my-code call
  - `referral_redemptions`  one row per invitee using someone's code
                            (UNIQUE on invitee_id — operator policy:
                            «один код на аккаунт за всю историю»)

Also seeds four `app_settings` rows so the policy is editable from
the admin panel without a redeploy:

  - referral_inviter_stars  = 100
  - referral_inviter_days   = 7
  - referral_invitee_stars  = 30
  - referral_invitee_days   = 7

Idempotent on `app_settings` seeds — uses ON CONFLICT DO NOTHING so
re-running the migration on a partially-seeded DB stays safe.

Revision ID: c1e2d3f4a5b6
Revises: f3c4d5e6a8b9
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1e2d3f4a5b6"
down_revision: Union[str, None] = "f3c4d5e6a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "referral_codes",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_referral_codes_code"),
    )
    op.create_index("ix_referral_codes_code", "referral_codes", ["code"])

    op.create_table(
        "referral_redemptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "code_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("referral_codes.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inviter_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitee_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("inviter_stars_granted", sa.Integer, nullable=False),
        sa.Column("inviter_days_granted", sa.Integer, nullable=False),
        sa.Column("invitee_stars_granted", sa.Integer, nullable=False),
        sa.Column("invitee_days_granted", sa.Integer, nullable=False),
        sa.UniqueConstraint("invitee_id", name="uq_referral_redemptions_invitee"),
    )
    op.create_index(
        "ix_referral_redemptions_code_id", "referral_redemptions", ["code_id"]
    )
    op.create_index(
        "ix_referral_redemptions_inviter_id", "referral_redemptions", ["inviter_id"]
    )

    # Seed policy values. ON CONFLICT keeps the migration safe to
    # re-run if a partial seed already happened.
    op.execute(
        """
        INSERT INTO app_settings (key, value, description) VALUES
          ('referral_inviter_stars', '100',
           'Звёзды (очки лидерборда), которые получает приглашающий за каждое успешное использование его реферального кода.'),
          ('referral_inviter_days',  '7',
           'Дней Pro-подписки приглашающему за каждое успешное использование кода.'),
          ('referral_invitee_stars', '30',
           'Звёзды приглашённому в момент ввода чужого реферального кода.'),
          ('referral_invitee_days',  '7',
           'Дней Pro-подписки приглашённому при вводе кода.')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app_settings WHERE key IN (
          'referral_inviter_stars', 'referral_inviter_days',
          'referral_invitee_stars', 'referral_invitee_days'
        );
        """
    )
    op.drop_index("ix_referral_redemptions_inviter_id", table_name="referral_redemptions")
    op.drop_index("ix_referral_redemptions_code_id", table_name="referral_redemptions")
    op.drop_table("referral_redemptions")
    op.drop_index("ix_referral_codes_code", table_name="referral_codes")
    op.drop_table("referral_codes")
