"""daily_notification_template singleton table + seed default row

Moves the daily push notification config from hardcoded env-var defaults
into an admin-editable DB row. One singleton row (id=1) holds title, body,
hour, minute, and timezone. The daily scheduler re-reads this row on every
tick so changes propagate without a redeploy.

Seeds with the existing defaults so the scheduler behaves identically
to before on first deploy.

Revision ID: b2c3d4e5f6a7
Revises: a9b8c7d6e5f4
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_notification_template",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column(
            "hour",
            sa.Integer,
            nullable=False,
            server_default=sa.text("9"),
        ),
        sa.Column(
            "minute",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'Asia/Almaty'"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_daily_notification_template_singleton"),
        sa.CheckConstraint(
            "hour BETWEEN 0 AND 23",
            name="ck_daily_notification_template_hour",
        ),
        sa.CheckConstraint(
            "minute BETWEEN 0 AND 59",
            name="ck_daily_notification_template_minute",
        ),
    )

    op.execute(
        """
        INSERT INTO daily_notification_template
          (id, enabled, title, body, hour, minute, timezone)
        VALUES
          (
            1,
            true,
            'Новые ежедневные задания уже ждут тебя!',
            'Открывай приложение AIMA и решай свежий тест!',
            9,
            0,
            'Asia/Almaty'
          )
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("daily_notification_template")
