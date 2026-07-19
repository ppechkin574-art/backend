"""add crm task attachments, links, extra assignees, comments

Revision ID: c5d9f3a2b1e7
Revises: b4c8e2a1f6d3
Create Date: 2026-07-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5d9f3a2b1e7"
down_revision: Union[str, None] = "b4c8e2a1f6d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- attachments ----------
    op.create_table(
        "crm_task_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("crm_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_name", sa.String(600), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uploaded_by_display", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_crm_task_attachments_task_id", "crm_task_attachments", ["task_id"]
    )

    # ---------- links ("связано с") ----------
    op.create_table(
        "crm_task_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("crm_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "linked_task_id",
            sa.Integer(),
            sa.ForeignKey("crm_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "linked_task_id", name="uq_crm_task_links_pair"),
    )
    op.create_index("ix_crm_task_links_task_id", "crm_task_links", ["task_id"])

    # ---------- extra assignees ----------
    op.create_table(
        "crm_task_assignees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("crm_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_display", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_id", "admin_id", name="uq_crm_task_assignees_pair"
        ),
    )
    op.create_index(
        "ix_crm_task_assignees_task_id", "crm_task_assignees", ["task_id"]
    )

    # ---------- comments ----------
    op.create_table(
        "crm_task_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("crm_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_display", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_crm_task_comments_task_id", "crm_task_comments", ["task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_crm_task_comments_task_id", table_name="crm_task_comments")
    op.drop_table("crm_task_comments")

    op.drop_index("ix_crm_task_assignees_task_id", table_name="crm_task_assignees")
    op.drop_table("crm_task_assignees")

    op.drop_index("ix_crm_task_links_task_id", table_name="crm_task_links")
    op.drop_table("crm_task_links")

    op.drop_index(
        "ix_crm_task_attachments_task_id", table_name="crm_task_attachments"
    )
    op.drop_table("crm_task_attachments")
