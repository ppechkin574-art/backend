"""question_drafts table — AI question-generator review pipeline

Adds the `question_drafts` staging table. AI-generated questions land
here as `draft` rows; a human reviews / edits in the admin panel, then
publishes — which creates a real `questions` row through the existing
question create service and flips the draft to `published`.

Additive only: no change to `questions` / `variants` / `question_blocks`
or any existing enum. Creates ONE new native enum type `draftstatus`
and reuses the already-present `difficulty` / `questiontype` types
(create_type=False) for the corresponding columns.

Revision ID: d8f1a2b3c4e5
Revises: d7e8f9a0b1c2
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8f1a2b3c4e5"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enum for the draft lifecycle. We create it EXPLICITLY (with
    # checkfirst) and pass create_type=False to the column references
    # below so `create_table` does NOT emit a second, un-guarded
    # CREATE TYPE (which would fail on the already-created type).
    bind = op.get_bind()
    postgresql.ENUM(
        "draft",
        "approved",
        "rejected",
        "published",
        name="draftstatus",
    ).create(bind, checkfirst=True)
    draft_status_enum = postgresql.ENUM(
        "draft",
        "approved",
        "rejected",
        "published",
        name="draftstatus",
        create_type=False,
    )

    # Reuse the existing native enum types (already in the DB) — do NOT
    # re-create them. Same pattern as a43fc4cdc2f0_module_system.
    difficulty_enum = postgresql.ENUM(
        "easy", "medium", "hard", name="difficulty", create_type=False
    )
    question_type_enum = postgresql.ENUM(
        "single_choice",
        "multiple_choice",
        "matching",
        name="questiontype",
        create_type=False,
    )

    op.create_table(
        "question_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guid", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("subject_name", sa.String(), nullable=True),
        sa.Column("topic_name", sa.String(), nullable=True),
        sa.Column("difficulty", difficulty_enum, nullable=True),
        sa.Column(
            "question_type",
            question_type_enum,
            nullable=False,
            server_default="single_choice",
        ),
        sa.Column("blocks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("variants", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("task_description_ru", sa.Text(), nullable=True),
        sa.Column("task_description_kk", sa.Text(), nullable=True),
        sa.Column("question_translation_ru", sa.Text(), nullable=True),
        sa.Column("question_translation_kk", sa.Text(), nullable=True),
        sa.Column("explanation_ru", sa.Text(), nullable=True),
        sa.Column("explanation_kk", sa.Text(), nullable=True),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            draft_status_enum,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("validation", sa.JSON(), nullable=True),
        sa.Column("dedup_of_question_id", sa.Integer(), nullable=True),
        sa.Column("published_question_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dedup_of_question_id"], ["questions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["published_question_id"], ["questions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guid", name="uq_question_drafts_guid"),
    )
    op.create_index(
        "ix_question_drafts_status", "question_drafts", ["status"], unique=False
    )
    op.create_index(
        "ix_question_drafts_subject_id",
        "question_drafts",
        ["subject_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_question_drafts_subject_id", table_name="question_drafts")
    op.drop_index("ix_question_drafts_status", table_name="question_drafts")
    op.drop_table("question_drafts")
    # Drop the enum type we created (only ours — leave difficulty /
    # questiontype intact).
    postgresql.ENUM(name="draftstatus").drop(op.get_bind(), checkfirst=True)
