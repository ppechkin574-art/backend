"""Import Math variant kk translations from seed JSON (Phase 7b pilot)

Sister migration to `c4e9d6f7b8a2` (which populated questions.question_text_kk
+ hint_text_kk).  Reads `scripts/data/math_kk_variants_pilot.json` —
one entry per Math question_id with an ordered list of kk-variant
strings (4 per question, matches DB shape) — and UPDATEs
`variants.variant_text_kk` paired by ordinal index after sorting DB
variants by id ASC.

Why ordinal-by-id pairing
-------------------------
The source JSON variants are positional strings (no per-variant
identifier).  They were exported FROM this database on 25.04.2026,
so ORDER BY variants.id at export time matched the source array
order.  Variants haven't been re-inserted since (only data updates,
which don't change id ordering), so the same ordering reproduces here.

Idempotent UPDATE: re-running this migration rewrites the same kk
text into the same rows — no corruption.  Variants whose source
string is None/empty are skipped (leaves the column NULL → RU
fallback at read time).

Edge cases
----------
* Source has 4 variants for a question, DB has fewer (or more) →
  pair as many as exist on both sides; log the mismatch so we can
  investigate later.
* Source string is identical to the RU variant in DB (LaTeX formulas
  like `r"\\frac{1}{4}"`, plain numbers like `"0"`) → still written
  to `variant_text_kk`; downstream helper no-ops when the kk string
  equals the current rendering.

Revision ID: e7d8c9b1a2f3
Revises: e1a2b3c4d5e6
Create Date: 2026-05-22
"""

import json
import logging
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7d8c9b1a2f3"
down_revision: Union[str, None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "data"
    / "math_kk_variants_pilot.json"
)


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")

    if not _SEED_PATH.exists():
        log.warning(
            "Phase 7b variants: %s not found — check Dockerfile COPY layer",
            _SEED_PATH,
        )
        return

    with _SEED_PATH.open("r", encoding="utf-8") as fh:
        entries = json.load(fh)

    log.info(
        "Phase 7b variants: importing kk strings for %d Math questions",
        len(entries),
    )

    connection = op.get_bind()

    # 1) Resolve question_id → ordered variant ids in ONE round-trip.
    # Per-row SELECTs in a loop pushed the deploy past the 30s
    # healthcheck window — see Railway failed deploy 22.05.2026 21:40.
    question_ids = [
        e["question_id"] for e in entries if e.get("question_id")
    ]
    if not question_ids:
        log.info("Phase 7b variants: seed has no question_ids; nothing to do")
        return

    id_rows = connection.execute(
        sa.text(
            "SELECT question_id, id FROM variants "
            "WHERE question_id IN :ids ORDER BY question_id, id"
        ).bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": question_ids},
    ).fetchall()
    qid_to_variant_ids: dict[int, list[int]] = {}
    for qid, vid in id_rows:
        qid_to_variant_ids.setdefault(qid, []).append(vid)

    # 2) Build flat (variant_id, kk_str) pairs.  Skip empty kk strings
    # (leaves variant_text_kk NULL → RU fallback at read time).
    update_pairs: list[tuple[int, str]] = []
    skipped_empty = 0
    mismatched: list[tuple[int, int, int]] = []
    for entry in entries:
        question_id = entry.get("question_id")
        src_variants = entry.get("variants") or []
        if not question_id or not src_variants:
            continue
        db_ids = qid_to_variant_ids.get(question_id, [])
        if len(db_ids) != len(src_variants):
            mismatched.append((question_id, len(src_variants), len(db_ids)))
        for variant_id, kk_str in zip(db_ids, src_variants):
            if not kk_str:
                skipped_empty += 1
                continue
            update_pairs.append((variant_id, kk_str))

    # 3) Bulk UPDATE in a single statement via Postgres `unnest`.  Two
    # parallel arrays unzip into a virtual `(id, kk)` table that joins
    # against `variants` by id.  ~750 rows ship as two array params.
    if update_pairs:
        ids_arr = [p[0] for p in update_pairs]
        kk_arr = [p[1] for p in update_pairs]
        connection.execute(
            sa.text(
                """
                UPDATE variants
                SET variant_text_kk = u.kk
                FROM unnest(CAST(:ids AS integer[]), CAST(:kk AS text[]))
                     AS u(id, kk)
                WHERE variants.id = u.id
                """
            ),
            {"ids": ids_arr, "kk": kk_arr},
        )

    log.info(
        "Phase 7b variants: updated=%d skipped_empty=%d mismatched_questions=%d",
        len(update_pairs),
        skipped_empty,
        len(mismatched),
    )
    if mismatched:
        log.warning(
            "Phase 7b variants: %d questions had count mismatch (first 5: %s)",
            len(mismatched),
            mismatched[:5],
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE variants SET variant_text_kk = NULL")
    )
