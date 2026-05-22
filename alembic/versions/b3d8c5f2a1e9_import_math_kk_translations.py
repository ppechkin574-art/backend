"""Bulk-import Kazakh translations for «Математика» questions (Phase 7b pilot)

Data migration — UPDATE-only, no schema change.  Reads
`scripts/data/math_kk_pilot.json` (174 entries pre-filtered to the Math
subject) and populates the `questions.question_text_kk` /
`questions.hint_text_kk` columns added by the previous migration
(`a7c4f9e1b2d8`).

Why this is in alembic (not a one-off `python scripts/...py` invocation):
─ Railway runs `alembic upgrade head` as part of the Docker CMD, so
  this migration applies automatically on the next deploy.  Operator
  doesn't need shell access or local `pip install alembic psycopg`.
─ Alembic tracks application — repeated deploys won't re-import the
  same 174 rows.  The standalone import script (`scripts/import_kk_
  translations.py`) is kept for ad-hoc back-fills of other subjects
  once they're translated.

`upgrade()` is idempotent within a single run (only UPDATEs rows that
exist; logs counts).  `downgrade()` clears the kk columns for every
question — destructive but cheap to re-run upgrade afterwards.

Revision ID: b3d8c5f2a1e9
Revises: a7c4f9e1b2d8
Create Date: 2026-05-22
"""

import json
import logging
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d8c5f2a1e9"
down_revision: Union[str, None] = "a7c4f9e1b2d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Locate the seed file relative to the project root.  Alembic runs from
# the repo root inside the Railway container, so this path resolves to
# /app/scripts/data/math_kk_pilot.json after the Dockerfile COPY step.
_SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "data"
    / "math_kk_pilot.json"
)


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")

    if not _SEED_PATH.exists():
        # In environments where the data file wasn't shipped (e.g. a
        # subset of CI), skip silently — the migration tracker still
        # marks it applied so future deploys don't retry.
        log.warning(
            "Phase 7b: math_kk_pilot.json not found at %s — skipping bulk import",
            _SEED_PATH,
        )
        return

    with _SEED_PATH.open("r", encoding="utf-8") as fh:
        entries = json.load(fh)

    log.info("Phase 7b: importing %d Math KK translations", len(entries))

    connection = op.get_bind()
    updated = 0
    missing = 0
    for entry in entries:
        question_id = entry.get("question_id")
        question_text = entry.get("question_text")
        hint_text = entry.get("hint_text") or None

        if not question_id or not question_text:
            continue

        result = connection.execute(
            sa.text(
                """
                UPDATE questions
                SET question_text_kk = :qtext,
                    hint_text_kk = :htext
                WHERE id = :qid
                """
            ),
            {"qtext": question_text, "htext": hint_text, "qid": question_id},
        )
        if result.rowcount:
            updated += result.rowcount
        else:
            missing += 1

    log.info(
        "Phase 7b: imported %d Math KK rows (%d question_ids missing from DB)",
        updated,
        missing,
    )


def downgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")
    connection = op.get_bind()
    result = connection.execute(
        sa.text(
            """
            UPDATE questions
            SET question_text_kk = NULL,
                hint_text_kk = NULL
            WHERE question_text_kk IS NOT NULL
               OR hint_text_kk IS NOT NULL
            """
        )
    )
    log.info("Phase 7b downgrade: cleared kk columns on %d questions", result.rowcount)
