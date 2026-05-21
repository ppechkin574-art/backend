"""kk-translation cache columns for questions + topics (Phase 7b pilot)

Adds three nullable columns that mirror existing Russian content fields:

  * questions.question_text_kk  — denormalised Kazakh body text per question
  * questions.hint_text_kk      — denormalised Kazakh hint text (kept on the
                                  question row instead of joining through
                                  the `hints` table — pilot simplification,
                                  see PRODUCT_ROADMAP Phase 7b note)
  * topics.name_kk              — Kazakh topic name

All three are nullable: the column ships empty for the whole catalogue
and the import script (`scripts/import_kk_translations.py`) populates
Mathematics rows only for the pilot.  Other subjects fall back to RU on
read (api/dto-side fallback logic), no breakage.

Variant B from the architecture decision: we don't parse the JSON
export back into the `text_blocks` rendering structure.  The Flutter
client still receives the same DTO shape — only the textual content
inside changes when Accept-Language: kk and the cache column is non-null.

Revision ID: a7c4f9e1b2d8
Revises: e5a2b8d3c7f1
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7c4f9e1b2d8"
down_revision: Union[str, Sequence[str], None] = "e5a2b8d3c7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("question_text_kk", sa.Text(), nullable=True),
    )
    op.add_column(
        "questions",
        sa.Column("hint_text_kk", sa.Text(), nullable=True),
    )
    op.add_column(
        "topics",
        sa.Column("name_kk", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("topics", "name_kk")
    op.drop_column("questions", "hint_text_kk")
    op.drop_column("questions", "question_text_kk")
