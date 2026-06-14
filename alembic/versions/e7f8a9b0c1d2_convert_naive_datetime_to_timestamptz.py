"""convert naive datetime columns to timestamptz

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-15

All affected columns stored UTC values (Railway server runs UTC), so the
USING clause safely re-tags them as UTC without shifting the instant.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # trainer_attempts
    op.alter_column(
        "trainer_attempts", "started_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="started_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "trainer_attempts", "completed_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="completed_at AT TIME ZONE 'UTC'",
    )

    # trainer_attempt_answers
    op.alter_column(
        "trainer_attempt_answers", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "trainer_attempt_answers", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # daily_test_subject_preferences
    op.alter_column(
        "daily_test_subject_preferences", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "daily_test_subject_preferences", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # daily_test_attempts
    op.alter_column(
        "daily_test_attempts", "started_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="started_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "daily_test_attempts", "completed_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="completed_at AT TIME ZONE 'UTC'",
    )

    # daily_test_answers
    op.alter_column(
        "daily_test_answers", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )

    # daily_test_device_tokens
    op.alter_column(
        "daily_test_device_tokens", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "daily_test_device_tokens", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # subscription_plans
    op.alter_column(
        "subscription_plans", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "subscription_plans", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # subscriptions
    op.alter_column(
        "subscriptions", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "subscriptions", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # subscription_history
    op.alter_column(
        "subscription_history", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )

    # payments
    op.alter_column(
        "payments", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "payments", "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    # payment_status_history
    op.alter_column(
        "payment_status_history", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )

    # cards
    op.alter_column(
        "cards", "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    # Revert to TIMESTAMP WITHOUT TIME ZONE (strips tz info, keeps UTC value)
    for table, col in [
        ("trainer_attempts", "started_at"),
        ("trainer_attempts", "completed_at"),
        ("trainer_attempt_answers", "created_at"),
        ("trainer_attempt_answers", "updated_at"),
        ("daily_test_subject_preferences", "created_at"),
        ("daily_test_subject_preferences", "updated_at"),
        ("daily_test_attempts", "started_at"),
        ("daily_test_attempts", "completed_at"),
        ("daily_test_answers", "created_at"),
        ("daily_test_device_tokens", "created_at"),
        ("daily_test_device_tokens", "updated_at"),
        ("subscription_plans", "created_at"),
        ("subscription_plans", "updated_at"),
        ("subscriptions", "created_at"),
        ("subscriptions", "updated_at"),
        ("subscription_history", "created_at"),
        ("payments", "created_at"),
        ("payments", "updated_at"),
        ("payment_status_history", "created_at"),
        ("cards", "created_at"),
    ]:
        op.alter_column(
            table, col,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )
