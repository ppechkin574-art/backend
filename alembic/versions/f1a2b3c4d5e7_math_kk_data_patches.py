"""Targeted kk-text patches for Math pilot residue (Phase 7b)

Two unrelated fixes bundled because they're both one-row UPDATEs and
neither warrants its own seed file:

1. **NULL kk for 4 structurally-broken qids.** The Kazakh translator
   mangled the LaTeX delimiters on these — kk strings either wrap
   Kazakh prose *inside* `\\begin{cases}` / `r"..."` blocks or break
   the closing brace.  flutter_math_fork falls back to plain text and
   the operator sees a wall of raw `\\begin{cases}` / `\\frac{...}` /
   `r"..."` characters mid-question (sim screenshots 22.05.2026).
   We can't repair the source without re-translation, so nullify the
   kk column → frontend falls back to RU which has proper LaTeX
   delimiters and renders correctly:

     * 4252 — «теңсіздіктер жүйесін» wrapped inside `\\begin{cases}`
     * 4289 — `\\((x_{1};y_{1})` mixed with `r"..."` + broken `xses}`
     * 4354 — broken `\\mathbf{d}` chain with stray `\\xa0` padding
     * 4361 — `r"\\left` opens but never closes; Kazakh prose inside

   qid 4271 (also has cyrillic env names) is left intact — the
   companion sanitizer change on the Flutter side maps
   `\\begin{массив}` → `\\begin{array}` etc., so it may render.

   Variant kk for those 4 qids is also nullified — mixing RU question
   with kk variants looks worse than full RU.

2. **Add kk_text for qid 4325** — the one Math question that had an
   empty `question_text` in the source export.  Manual one-liner:
   «Вычислите ...» → «Есептеңіз: ...».  The formula stays in raw
   LaTeX inline; my multi-block splice keeps trailing media blocks
   intact, so the rendered formula card survives.

Revision ID: f1a2b3c4d5e7
Revises: e7d8c9b1a2f3
Create Date: 2026-05-22
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, None] = "e7d8c9b1a2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NULLIFY_QUESTION_IDS = (4252, 4289, 4354, 4361)

# qid 4325 — «Вычислите log_4 12 / log_{12} 4 - log_4 48 · log_4 3»
# Manual kk: same formula, Kazakh imperative.  Formula stays raw-LaTeX
# inside `r"..."` so the existing `latexRegex` on the client picks it
# up and feeds it to flutter_math_fork.
_QID_4325_KK_TEXT = (
    'Есептеңіз: r"\\frac{\\log_4 12} {\\log_{12} 4}'
    '-\\log_4 48 \\cdot\\log_4 3".'
)


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")
    conn = op.get_bind()

    # 1) Null the four structurally-broken kk strings + their variants.
    conn.execute(
        sa.text(
            "UPDATE questions SET question_text_kk = NULL, "
            "hint_text_kk = NULL WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(_NULLIFY_QUESTION_IDS)},
    )
    conn.execute(
        sa.text(
            "UPDATE variants SET variant_text_kk = NULL "
            "WHERE question_id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(_NULLIFY_QUESTION_IDS)},
    )
    log.info(
        "Phase 7b patches: nullified kk for %d structurally-broken qids: %s",
        len(_NULLIFY_QUESTION_IDS),
        list(_NULLIFY_QUESTION_IDS),
    )

    # 2) Add manually-translated kk for qid 4325 (no source entry).
    result = conn.execute(
        sa.text(
            "UPDATE questions SET question_text_kk = :v WHERE id = :id"
        ),
        {"v": _QID_4325_KK_TEXT, "id": 4325},
    )
    log.info(
        "Phase 7b patches: set kk for qid 4325 (rows updated=%s)",
        result.rowcount,
    )


def downgrade() -> None:
    # Best-effort downgrade — we can't recover the original kk content
    # for the nullified rows (they were broken anyway).  The qid 4325
    # kk row is cleared.
    op.get_bind().execute(
        sa.text("UPDATE questions SET question_text_kk = NULL WHERE id = 4325")
    )
