"""Rename Pro → Month in referral_*_days descriptions

Subscription plan was rebranded «Pro» → «Month» a while back (the
iOS app already shows «Month жазылымы» on the profile). The two
referral_*_days seed descriptions were written using the old name;
update them so the generic Настройки сервиса view in the admin
shows the current brand name. The values themselves don't change —
only the `description` column, which is the operator-visible label.

Idempotent: UPDATE just rewrites the same rows. Safe to re-run.

Revision ID: c2f3a4b5c6d7
Revises: c1e2d3f4a5b6
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c2f3a4b5c6d7"
down_revision: Union[str, None] = "c1e2d3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE app_settings
        SET description = 'Дней подписки Month приглашающему за каждое успешное использование кода.'
        WHERE key = 'referral_inviter_days';
        """
    )
    op.execute(
        """
        UPDATE app_settings
        SET description = 'Дней подписки Month приглашённому при вводе кода.'
        WHERE key = 'referral_invitee_days';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_settings
        SET description = 'Дней Pro-подписки приглашающему за каждое успешное использование кода.'
        WHERE key = 'referral_inviter_days';
        """
    )
    op.execute(
        """
        UPDATE app_settings
        SET description = 'Дней Pro-подписки приглашённому при вводе кода.'
        WHERE key = 'referral_invitee_days';
        """
    )
