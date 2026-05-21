#!/usr/bin/env python3
"""One-shot bulk import of Kazakh question/hint text into the kk-cache
columns added by alembic migration `a7c4f9e1b2d8`.

Phase 7b pilot scope: only rows where `subject_name == "Математика"`
are written.  Other subjects are counted but skipped so we can verify
the round-trip on a single subject before opening the floodgates.

Source data
-----------
JSON array at /Users/macbookpro/mare-ent-db/data/questions_export_kk.json
(3.84 MB at the time of writing).  Each entry has:

    {
      "question_id": 4202,             # matches questions.id
      "subject_name": "Математика",    # stays Russian — backend key
      "topic_name":  "Теңдеу",         # Kazakh — NOT imported in pilot
      "question_text": "...",
      "hint_text":     "...",
      "variants": [...]                # NOT imported in pilot
    }

Behaviour
---------
* Connects via DATABASE_URL (same env var the prod stack uses).
* Filters entries to Mathematics.
* For each entry runs:

      UPDATE questions
         SET question_text_kk = :q,
             hint_text_kk     = :h
       WHERE id = :id

  Idempotent — re-running on the same data is a no-op
  (UPDATE, not INSERT; same content → same result).
* Counts matched/unmatched/skipped rows and prints a one-line summary.
* `--dry-run` (default) runs SELECT-only and prints what WOULD happen
  without writing anything.  Use `--apply` to actually commit.

Why not topic_name in pilot?
----------------------------
The JSON exposes `topic_name` already-in-Kazakh — we'd need the
RU↔KK topic mapping to UPDATE `topics.name_kk WHERE name = <RU>`,
and that mapping doesn't exist in the export.  Topic translation
ships in a follow-up that adds a `topic_name_ru` column or a
sidecar mapping CSV.

Usage
-----
    cd aima-backend
    DATABASE_URL=postgresql://... python3 scripts/import_kk_translations.py
    DATABASE_URL=postgresql://... python3 scripts/import_kk_translations.py --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import psycopg


DEFAULT_JSON_PATH = Path("/Users/macbookpro/mare-ent-db/data/questions_export_kk.json")
PILOT_SUBJECT = "Математика"

logger = logging.getLogger("import_kk")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_entries(path: Path) -> list[dict]:
    if not path.exists():
        logger.error("Source JSON not found: %s", path)
        sys.exit(2)
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        logger.error("Expected top-level JSON array, got %s", type(data).__name__)
        sys.exit(2)
    return data


def _filter_pilot(entries: list[dict]) -> tuple[list[dict], int]:
    """Split entries into (pilot_subject_entries, skipped_count)."""
    pilot = []
    skipped = 0
    for e in entries:
        if e.get("subject_name") == PILOT_SUBJECT:
            pilot.append(e)
        else:
            skipped += 1
    return pilot, skipped


def _existing_ids(cur: psycopg.Cursor, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    cur.execute("SELECT id FROM questions WHERE id = ANY(%s)", (ids,))
    return {row[0] for row in cur.fetchall()}


def _apply_updates(
    cur: psycopg.Cursor, entries: list[dict], existing: set[int]
) -> int:
    """Run the UPDATE statements; return count of rows updated."""
    updated = 0
    for e in entries:
        qid = e.get("question_id")
        if qid not in existing:
            continue
        cur.execute(
            """
            UPDATE questions
               SET question_text_kk = %s,
                   hint_text_kk     = %s
             WHERE id = %s
            """,
            (e.get("question_text"), e.get("hint_text"), qid),
        )
        # cur.rowcount: 1 when the row exists (we already checked).
        updated += cur.rowcount or 0
    return updated


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes; without this flag the script runs in dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default behaviour). Mutually exclusive with --apply.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to the kk-export JSON (default: {DEFAULT_JSON_PATH})",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        logger.error("Pass either --apply or --dry-run, not both.")
        return 2

    write = bool(args.apply)
    mode = "APPLY" if write else "DRY-RUN"

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL env var is required.")
        return 2

    entries = _load_entries(args.source)
    logger.info("Loaded %d entries from %s", len(entries), args.source)

    pilot, skipped_other_subjects = _filter_pilot(entries)
    logger.info(
        "Mode=%s  pilot_subject=%r  pilot_entries=%d  skipped_other_subjects=%d",
        mode,
        PILOT_SUBJECT,
        len(pilot),
        skipped_other_subjects,
    )

    pilot_ids = [e.get("question_id") for e in pilot if isinstance(e.get("question_id"), int)]

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            existing = _existing_ids(cur, pilot_ids)
            missing = [qid for qid in pilot_ids if qid not in existing]
            logger.info(
                "DB lookup: matched=%d  missing_in_db=%d",
                len(existing),
                len(missing),
            )
            if missing:
                # Cap the noise — log a few sample IDs only.
                logger.warning("Missing question_ids (first 20): %s", missing[:20])

            if not write:
                logger.info(
                    "DRY-RUN: would UPDATE %d rows. "
                    "Re-run with --apply to write.",
                    len(existing),
                )
                return 0

            updated = _apply_updates(cur, pilot, existing)
        conn.commit()
        logger.info("APPLY complete: %d rows updated, transaction committed.", updated)

    return 0


if __name__ == "__main__":
    sys.exit(main())
