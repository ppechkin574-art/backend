"""app_update_config singleton table + seed default row

Moves the mobile force-update config from Railway env vars into an
admin-editable DB row. One singleton row (id=1) holds per-platform
`min_build` + `store_url`. The public `GET /app/update-config` reads it;
the admin panel edits it — no redeploy needed to force an update.

Seeds the singleton with zeros / empty strings so the public endpoint
has a row to read on first boot (min_build=0 → app never force-updates).

Revision ID: a9b8c7d6e5f4
Revises: d8f1a2b3c4e5
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "d8f1a2b3c4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_update_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "ios_min_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "android_min_build",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "ios_store_url",
            sa.String,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "android_store_url",
            sa.String,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_by", sa.String, nullable=True),
    )

    # Seed the singleton row so the public endpoint always has something
    # to read. id=1 fixed; zeros/empty → app never force-updates until an
    # admin raises min_build from the panel.
    op.execute(
        """
        INSERT INTO app_update_config
          (id, ios_min_build, android_min_build, ios_store_url, android_store_url)
        VALUES
          (1, 0, 0, '', '')
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("app_update_config")
