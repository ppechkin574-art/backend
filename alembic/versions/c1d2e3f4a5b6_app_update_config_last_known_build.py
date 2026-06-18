"""app_update_config: add per-platform last_known_build store guard

Adds `ios_last_known_build` / `android_last_known_build` to the singleton
`app_update_config` row. These hold the highest build that is ACTUALLY
live in each platform's store (operator-maintained). The admin PUT
rejects `min_build > last_known_build`, so an operator can no longer
force users onto a version that is not yet published (= bricked app +
Apple 2.1 review-reject risk). 0 = unknown -> no hard guard, panel warns.

Additive only: two nullable=False Integer columns with server_default
"0", so the existing seeded singleton row backfills to 0 automatically.

Revision ID: c1d2e3f4a5b6
Revises: e7f8a9b0c1d2
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_update_config",
        sa.Column(
            "ios_last_known_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "app_update_config",
        sa.Column(
            "android_last_known_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_update_config", "android_last_known_build")
    op.drop_column("app_update_config", "ios_last_known_build")
