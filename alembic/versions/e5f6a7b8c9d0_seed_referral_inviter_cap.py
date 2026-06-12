"""Seed referral_inviter_max_rewards app-setting (anti-farm cap)

Adds the admin-tunable cap on how many invitees an inviter earns a
reward for. Past the cap the invitee still gets their bonus but the
inviter earns nothing — neutralises self-code farming via throwaway
accounts. Default 25; 0 disables the inviter reward entirely.

The feature works WITHOUT this row (ReferralService falls back to the
hard-coded default 25) — this seed just surfaces the knob in the admin
panel alongside the other referral policy settings.

Idempotent — ON CONFLICT DO NOTHING keeps re-runs safe.

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value, description) VALUES
          ('referral_inviter_max_rewards', '25',
           'Анти-фарм: за сколько приглашённых максимум начисляется награда приглашающему. Сверх лимита приглашённый получает свой бонус, приглашающий — нет. 0 отключает награду приглашающему.')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM app_settings WHERE key = 'referral_inviter_max_rewards';"
    )
