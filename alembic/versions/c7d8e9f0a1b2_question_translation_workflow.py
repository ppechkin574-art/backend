"""question translation workflow: status column + glossary + config

- questions.translation_status_kk ('none' / 'draft' / 'done'), backfilled from
  question_text_kk (non-empty → 'done').
- translation_glossary — reusable ru→kk word pool per subject (NULL = global).
- translation_config — saved tone/length/instruction per subject.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "translation_status_kk",
            sa.String(),
            nullable=False,
            server_default="none",
        ),
    )
    op.create_index(
        "ix_questions_translation_status_kk",
        "questions",
        ["translation_status_kk"],
    )
    # Backfill: questions that already carry kk text are 'done'.
    op.execute(
        "UPDATE questions SET translation_status_kk = 'done' "
        "WHERE question_text_kk IS NOT NULL AND question_text_kk <> ''"
    )

    op.create_table(
        "translation_glossary",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "subject_id",
            sa.Integer,
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("term_ru", sa.String(), nullable=False),
        sa.Column("term_kk", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint("subject_id", "term_ru", name="uq_glossary_subject_term"),
    )
    op.create_index(
        "ix_translation_glossary_subject_id",
        "translation_glossary",
        ["subject_id"],
    )

    op.create_table(
        "translation_config",
        sa.Column(
            "subject_id",
            sa.Integer,
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tone", sa.String(), nullable=False, server_default="official"),
        sa.Column("length", sa.String(), nullable=False, server_default="keep"),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("translation_config")
    op.drop_index(
        "ix_translation_glossary_subject_id", table_name="translation_glossary"
    )
    op.drop_table("translation_glossary")
    op.drop_index(
        "ix_questions_translation_status_kk", table_name="questions"
    )
    op.drop_column("questions", "translation_status_kk")
