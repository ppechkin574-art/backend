"""seed score_spike_daily_limit app setting (fraud detector threshold)

Adds the `score_spike_daily_limit` row to `app_settings` (default "10000")
so the operator can tune the score-spike detector threshold from the admin
panel without a redeploy. The backend reads it via
`AppSettingsService.get_int("score_spike_daily_limit", 10000)`.
Idempotent (ON CONFLICT DO NOTHING).

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value, description) VALUES
          ('score_spike_daily_limit',
           '10000',
           'Анти-фрод: максимум очков за 24 часа до срабатывания детектора score_spike (risk=75). По умолчанию 10000. Редактируется администратором без перезапуска.')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'score_spike_daily_limit';")
