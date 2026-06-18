"""app_update_config_audit_log: append-only change history

Records every successful change to the singleton force-update config:
a JSONB snapshot of all fields BEFORE and AFTER, plus who/when. Powers
the admin history view + one-click rollback. Append-only.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_update_config_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("changed_by", sa.String, nullable=True),
        sa.Column(
            "before_values",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "after_values",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_app_update_config_audit_log_changed_at",
        "app_update_config_audit_log",
        ["changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_update_config_audit_log_changed_at",
        table_name="app_update_config_audit_log",
    )
    op.drop_table("app_update_config_audit_log")
