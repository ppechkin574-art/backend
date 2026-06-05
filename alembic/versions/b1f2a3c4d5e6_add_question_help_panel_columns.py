"""add question help-panel columns (task description + question translation, ru/kk)

Backs the «Что требует вопрос?» panel in the mobile test screen. Four nullable
Text columns on `questions`, authored in the admin, served by locale:
  * task_description_ru / task_description_kk      — what the question asks
  * question_translation_ru / question_translation_kk — the question text in
    that language (the original question stays in its source language; this is
    a side translation shown only inside the help panel).

All nullable; the app shows the panel only when the locale-resolved pair is
populated, so existing questions are unaffected.

Revision ID: b1f2a3c4d5e6
Revises: f4c5d6e7f8a9
Create Date: 2026-06-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1f2a3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "f4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("task_description_ru", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("task_description_kk", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("question_translation_ru", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("question_translation_kk", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "question_translation_kk")
    op.drop_column("questions", "question_translation_ru")
    op.drop_column("questions", "task_description_kk")
    op.drop_column("questions", "task_description_ru")
