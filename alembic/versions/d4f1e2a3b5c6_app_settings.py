"""app_settings table for admin-editable runtime config

Adds a key/value store for runtime configuration that should be editable
from the admin panel without redeploying the backend.

Seeded with two SMS-abuse defences:
  - sms_daily_cap: global daily SMS send cap (default 1000). Past this,
    /auth/code/request returns 503 and an alert email goes out.
  - sms_ip_daily_block: per-IP daily SMS request count that triggers a
    24h block on that IP (default 20).

Also merges the three previous heads (a1f0e7e3b4c2, bdab54e499a9,
fc858cd71edc) into one linear lineage so future migrations have a
single base to build on. `alembic upgrade head` in the Dockerfile
needs an unambiguous head, and three open branches would block any
later migration.

Revision ID: d4f1e2a3b5c6
Revises: a1f0e7e3b4c2, bdab54e499a9, fc858cd71edc
Create Date: 2026-05-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f1e2a3b5c6"
down_revision: Union[str, Sequence[str], None] = (
    "a1f0e7e3b4c2",
    "bdab54e499a9",
    "fc858cd71edc",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_SETTINGS = [
    {
        "key": "sms_daily_cap",
        "value": "1000",
        "description": (
            "Global daily SMS send cap. When today's counter exceeds this, "
            "/auth/code/request returns 503 and an alert email is sent. "
            "Counter resets at midnight UTC. Default 1000 ≈ 100 new users "
            "× 10 OTPs each with headroom."
        ),
    },
    {
        "key": "sms_ip_daily_block",
        "value": "20",
        "description": (
            "Per-IP daily SMS request count that triggers a 24h block on "
            "that IP. Legitimate users typically make 1-3 OTP requests "
            "per day; values above 20 indicate automated abuse. Counter "
            "resets at midnight UTC."
        ),
    },
]


def upgrade() -> None:
    table = op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.bulk_insert(table, SEED_SETTINGS)


def downgrade() -> None:
    op.drop_table("app_settings")
