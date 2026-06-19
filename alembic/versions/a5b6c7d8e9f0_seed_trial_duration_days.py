"""seed trial_duration_days app setting (admin-editable trial length)

Adds the `trial_duration_days` row to `app_settings` (default "1") so the
operator can change the free-trial length straight from the admin panel
(generic app-settings page). The backend reads it via
`AppSettingsService.get_int("trial_duration_days", 1)`; the row exists only to
make the value visible + editable in the admin UI. Idempotent
(ON CONFLICT DO NOTHING) so it's safe to re-run.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value, description) VALUES
          ('trial_duration_days', '1',
           'Длительность бесплатного пробного периода в днях. Выдаётся при первой регистрации по номеру телефона (и разово существующим пользователям при включённом TRIAL_PAYWALL_ENABLED). По умолчанию 1.')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'trial_duration_days';")
