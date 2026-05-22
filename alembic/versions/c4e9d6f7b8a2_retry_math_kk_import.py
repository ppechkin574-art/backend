"""Retry Math KK data import after seed file was force-added (Phase 7b pilot)

Sister migration to `b3d8c5f2a1e9` — re-runs the same JSON-driven UPDATE
against `questions.question_text_kk` / `hint_text_kk`.

Why a new revision instead of editing b3d8c5f2a1e9:
─ The first migration was already marked applied in `alembic_version`
  on Railway when the seed file was missing from the image
  (commit a095cbe force-added it AFTER c2048bc shipped the migration
  code).  Alembic doesn't re-run applied revisions, so the upgrade
  body silently no-op'd via the `_SEED_PATH.exists()` guard.
─ Editing b3d8c5f2a1e9 to remove the guard wouldn't help — alembic
  still considers it applied and skips it entirely.  A fresh revision
  is the only way to get the importer to execute against the now-
  present JSON.
─ Idempotent UPDATE: re-running this doesn't corrupt anything even
  if b3d8c5f2a1e9 had actually populated rows (it just rewrites the
  same kk text into the same id).

Revision ID: c4e9d6f7b8a2
Revises: b3d8c5f2a1e9
Create Date: 2026-05-22
"""

import json
import logging
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4e9d6f7b8a2"
down_revision: Union[str, None] = "b3d8c5f2a1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "data"
    / "math_kk_pilot.json"
)


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")

    if not _SEED_PATH.exists():
        log.warning(
            "Phase 7b retry: math_kk_pilot.json STILL not found at %s — "
            "check Dockerfile COPY layer ships the file",
            _SEED_PATH,
        )
        return

    with _SEED_PATH.open("r", encoding="utf-8") as fh:
        entries = json.load(fh)

    log.info("Phase 7b retry: importing %d Math KK translations", len(entries))

    connection = op.get_bind()
    updated = 0
    missing_ids: list[int] = []
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
            missing_ids.append(question_id)

    log.info(
        "Phase 7b retry: imported %d rows; %d question_ids missing from DB%s",
        updated,
        len(missing_ids),
        (
            f" (first 5: {missing_ids[:5]})"
            if missing_ids
            else ""
        ),
    )


def downgrade() -> None:
    # No-op: b3d8c5f2a1e9.downgrade() already clears the kk columns
    # globally; this retry doesn't add anything to undo separately.
    pass
