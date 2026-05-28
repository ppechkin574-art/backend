"""Streak-reminder push template — singleton settings row

Backs the «push за 8 ч до сгорания стрика» reminder. One row,
CHECK (id=1) enforced. Operator edits title/body/offset from the
/admin/streak-push-template page; the scheduled cron picks fresh
values on each tick so changes take effect within a day.

Revision ID: f4c5d6e7f8a9
Revises: e3b4c5d6e7f8
Create Date: 2026-05-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4c5d6e7f8a9"
down_revision: Union[str, None] = "e3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "streak_push_template",
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
            "hours_before_reset",
            sa.Integer,
            nullable=False,
            server_default=sa.text("8"),
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
        sa.CheckConstraint("id = 1", name="ck_streak_push_template_singleton"),
        sa.CheckConstraint(
            "hours_before_reset BETWEEN 1 AND 23",
            name="ck_streak_push_template_hours",
        ),
    )

    op.execute(
        """
        INSERT INTO streak_push_template (id, enabled, title, body, hours_before_reset, timezone) VALUES
          (
            1,
            true,
            'Не теряй стрик! 🔥',
            'У тебя {streak} дн. подряд. Зайди до полуночи — иначе серия сгорит.',
            8,
            'Asia/Almaty'
          )
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("streak_push_template")
