"""add crm board tables (tasks + activity log)

Revision ID: a3f7c1b9d2e4
Revises: b1c2d3e4f5a6
Create Date: 2026-07-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f7c1b9d2e4"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="mid"),
        sa.Column("assignee_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_display", sa.String(200), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "labels",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_crm_tasks_status", "crm_tasks", ["status", "sort_order"])

    op.create_table(
        "crm_activity_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_title", sa.String(200), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_display", sa.String(200), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_crm_activity_created_at", "crm_activity_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_crm_activity_created_at", table_name="crm_activity_log")
    op.drop_table("crm_activity_log")
    op.drop_index("ix_crm_tasks_status", table_name="crm_tasks")
    op.drop_table("crm_tasks")
