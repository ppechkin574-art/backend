"""Null kk for Ағылшын тілі (English) — AI translated the English content too

Operator caught this 22.05.2026 on a visual sim sweep: for the English-
language subject, the AI-aided source export translated EVERYTHING into
Kazakh, including the English content that's the actual test material.

  qid 599  «Зат есімнің дұрыс түрі Thank you for your … .»
           variants: [кеңес, кеңес береді, кеңес беру, кеңестер]
           (should be [advice, advises, advising, advices])

  qid 546  «Дұрыс пішін…. бүгін өте желді»
           variants: [Бар, Болды, Бар, Бұл]
           (should be «… very windy today» + [is, was, are, it is])

  qid 547  «Дұрыс нұсқа Біз… кейін –ing пішінін ҚОЛДАНМАЙМЫЗ…»
           variants: [Жеп көремін, Мен қарсы емеспін, …]
           (should keep English grammatical constructs)

This breaks the test for KZ-locale clients — the user can no longer
practise English because the test material is no longer in English.

Until a native-speaker pass produces a `english_kk_stems_only.json`
(stems and instructions translated, English content body preserved),
the safer choice is to NULL `question_text_kk` / `hint_text_kk` /
`variant_text_kk` for every question under subject='Ағылшын'. RU
fallback kicks in — the user sees RU stems + actual English content,
which preserves the test's pedagogical purpose.

Idempotent: re-running just sets the same rows to NULL again.

Revision ID: f3c4d5e6a8b9
Revises: f2b3c4d5e6a8
Create Date: 2026-05-22
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3c4d5e6a8b9"
down_revision: Union[str, None] = "f2b3c4d5e6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")
    conn = op.get_bind()

    # Resolve subject_id by name (Russian name, since that's what's
    # stored on subjects.name — Kazakh name «Ағылшын» is only in the
    # export file).
    subj_row = conn.execute(
        sa.text("SELECT id FROM subjects WHERE name = 'Английский'")
    ).first()
    if subj_row is None:
        log.warning(
            "f3c4d5e6a8b9: subject 'Английский' not found — nothing to nullify"
        )
        return
    subject_id = subj_row[0]

    q_result = conn.execute(
        sa.text(
            "UPDATE questions SET question_text_kk = NULL, "
            "hint_text_kk = NULL WHERE subject_id = :sid"
        ),
        {"sid": subject_id},
    )
    v_result = conn.execute(
        sa.text(
            "UPDATE variants v SET variant_text_kk = NULL "
            "FROM questions q WHERE v.question_id = q.id "
            "AND q.subject_id = :sid"
        ),
        {"sid": subject_id},
    )
    log.info(
        "f3c4d5e6a8b9: nullified kk for English subject "
        "(questions=%s, variants=%s)",
        q_result.rowcount,
        v_result.rowcount,
    )


def downgrade() -> None:
    # No reverse — we don't have the original kk strings handy and
    # they were broken anyway. Re-running the rollout migration
    # `f2b3c4d5e6a8` (or a future english-only seed import) is the
    # path forward.
    pass
