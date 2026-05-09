"""One-off DB fix for a single content typo: ``В ажнейшей`` (stray space
after capital В) appearing in question text — should read ``Важнейшей``.

Why a script instead of an alembic migration:
  * It's a content fix, not a schema fix.  Alembic is for DDL;
    pushing string-rewrite UPDATEs through it makes downgrades dangerous
    on a system where Roman keeps editing the same rows by hand.
  * One-shot, idempotent, and reversible from the JSON backup.

Usage
-----
    DATABASE_URL=postgresql://... python scripts/fix_typo_vazhneyshey.py --dry-run
    DATABASE_URL=postgresql://... python scripts/fix_typo_vazhneyshey.py --apply

Behavior
~~~~~~~~
* ``--dry-run`` (default) prints the affected rows and exits without
  writing.  Use this first to confirm matches.
* ``--apply`` writes a backup to ``/tmp/fix_typo_vazhneyshey_<ts>.json``
  and then runs the UPDATE inside a single transaction.  If anything
  raises, the whole batch rolls back.

Pattern
~~~~~~~
We look for the literal substring ``"В аж"`` (capital cyrillic В,
ASCII space, lowercase ``аж``).  This is narrow on purpose — content
authors do write legitimate ``В а...`` phrases (``В августе``,
``В аудитории``).  The typo we're fixing is unambiguously
``В ажнейш...``; we replace ``"В аж" -> "Важ"`` only when the next
character is ``н`` so we don't touch unrelated text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import psycopg

# Anchored on the typo we know about: "В ажнейш..." -> "Важнейш...".
# The script reports any other "В аж" hit it finds but does not auto-fix
# them — those go through manual review.
TYPO_PATTERN = re.compile(r"В\sаж(?=н)", flags=re.UNICODE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes; default is dry-run")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: set DATABASE_URL", file=sys.stderr)
        return 1

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, value
                FROM question_blocks
                WHERE value LIKE %s
                ORDER BY id
                """,
                ("%В аж%",),
            )
            rows = cur.fetchall()

        targets: list[tuple[int, str, str]] = []
        skipped: list[tuple[int, str]] = []
        for row_id, value in rows:
            new_value, n = TYPO_PATTERN.subn("Важ", value)
            if n > 0:
                targets.append((row_id, value, new_value))
            else:
                skipped.append((row_id, value))

        print(f"Matched (will fix): {len(targets)} rows")
        for row_id, before, after in targets:
            print(f"  #{row_id}")
            print(f"    -  {before[:120]}")
            print(f"    +  {after[:120]}")

        if skipped:
            print(f"\nSkipped — 'В аж' present but not 'В ажн' "
                  f"(needs human review): {len(skipped)} rows")
            for row_id, value in skipped:
                print(f"  #{row_id}: {value[:120]}")

        if not args.apply:
            print("\nDry-run only.  Re-run with --apply to write.")
            return 0

        if not targets:
            print("\nNothing to apply.")
            return 0

        backup_path = f"/tmp/fix_typo_vazhneyshey_{int(time.time())}.json"
        with open(backup_path, "w", encoding="utf-8") as fh:
            json.dump(
                [{"id": row_id, "value": before} for row_id, before, _ in targets],
                fh,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\nBackup written to {backup_path}")

        with conn.cursor() as cur:
            for row_id, _, after in targets:
                cur.execute(
                    "UPDATE question_blocks SET value = %s WHERE id = %s",
                    (after, row_id),
                )
        conn.commit()
        print(f"Applied {len(targets)} updates.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
