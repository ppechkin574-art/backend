"""app_update_config: add per-platform recommended_build (soft-update tier)

Adds `ios_recommended_build` / `android_recommended_build`. When
min_build <= running build < recommended_build the app shows a
DISMISSIBLE "update available" prompt (once/day) instead of the blocking
gate. 0 = no soft prompt. Additive, server_default "0" backfills the
existing singleton row.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_update_config",
        sa.Column(
            "ios_recommended_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "app_update_config",
        sa.Column(
            "android_recommended_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_update_config", "android_recommended_build")
    op.drop_column("app_update_config", "ios_recommended_build")
