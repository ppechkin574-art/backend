"""Import kk translations for the remaining 11 subjects (Phase 7b rollout)

After the Math pilot landed clean on 22.05.2026 the operator green-lit
expansion to the rest of the catalogue.  Same shape as the Math import
chain (`b3d8c5f2a1e9` + `e7d8c9b1a2f3`), just operating on the
non-Math slice of `questions_export_kk.json`:

  * Ағылшын                385 questions
  * Биология               356
  * Физика                 333
  * Дүниежүзілік тарих     310
  * Химия                  289
  * География              279
  * Құқық негіздері        232
  * Информатика            223
  * Қазақстан тарихы       120
  * Математикалық сауаттылық 60
  * Оқу сауаттылығы        60

Two seed files (force-added past `.gitignore` *.json):

  * scripts/data/all_subjects_kk_pilot.json          (2647 q+hint rows)
  * scripts/data/all_subjects_kk_variants_pilot.json (2603 questions /
                                                      11110 variants)

Both UPDATEs run as a single bulk statement via Postgres `unnest`
(arrays passed as bound parameters).  Per Railway 22.05.2026 incident
`2f83790`, per-row UPDATEs in a loop pushed the deploy past the 30s
healthcheck — the unnest path keeps it under a second.  Alembic also
now runs in `preDeployCommand` (railway.toml change `65f8ae2`), so
even a multi-megabyte UPDATE can't time out the web boot.

Math rows are NOT touched — the seed generator filtered them out, and
the 4 structurally-broken Math qids that we nullified in
`f1a2b3c4d5e7` stay null.

Re-running this migration is idempotent: same kk strings land on the
same ids.

Revision ID: f2b3c4d5e6a8
Revises: f1a2b3c4d5e7
Create Date: 2026-05-22
"""

import json
import logging
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2b3c4d5e6a8"
down_revision: Union[str, None] = "f1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "data"
)
_Q_SEED = _DATA_DIR / "all_subjects_kk_pilot.json"
_V_SEED = _DATA_DIR / "all_subjects_kk_variants_pilot.json"


def upgrade() -> None:
    log = logging.getLogger("alembic.runtime.migration")
    conn = op.get_bind()

    # ─── Questions + hint kk ──────────────────────────────────────
    if _Q_SEED.exists():
        with _Q_SEED.open("r", encoding="utf-8") as fh:
            q_entries = json.load(fh)

        q_pairs = []
        for entry in q_entries:
            qid = entry.get("question_id")
            qt = entry.get("question_text")
            ht = entry.get("hint_text") or None
            if not qid or not qt:
                continue
            q_pairs.append((qid, qt, ht))

        if q_pairs:
            ids = [p[0] for p in q_pairs]
            kks = [p[1] for p in q_pairs]
            hints = [p[2] for p in q_pairs]
            conn.execute(
                sa.text(
                    """
                    UPDATE questions
                    SET question_text_kk = COALESCE(u.kk, questions.question_text_kk),
                        hint_text_kk     = COALESCE(u.h,  questions.hint_text_kk)
                    FROM unnest(
                        CAST(:ids   AS integer[]),
                        CAST(:kks   AS text[]),
                        CAST(:hints AS text[])
                    ) AS u(id, kk, h)
                    WHERE questions.id = u.id
                    """
                ),
                {"ids": ids, "kks": kks, "hints": hints},
            )
            log.info(
                "Phase 7b rollout: imported kk text+hint for %d questions",
                len(q_pairs),
            )
        else:
            log.info("Phase 7b rollout: questions seed has no rows")
    else:
        log.warning(
            "Phase 7b rollout: %s not found — Dockerfile COPY layer?",
            _Q_SEED,
        )

    # ─── Variants kk (ordinal-by-id pairing) ─────────────────────
    if _V_SEED.exists():
        with _V_SEED.open("r", encoding="utf-8") as fh:
            v_entries = json.load(fh)

        question_ids = [
            e["question_id"] for e in v_entries if e.get("question_id")
        ]
        if question_ids:
            id_rows = conn.execute(
                sa.text(
                    "SELECT question_id, id FROM variants "
                    "WHERE question_id IN :ids ORDER BY question_id, id"
                ).bindparams(sa.bindparam("ids", expanding=True)),
                {"ids": question_ids},
            ).fetchall()
            qid_to_variant_ids: dict[int, list[int]] = {}
            for qid, vid in id_rows:
                qid_to_variant_ids.setdefault(qid, []).append(vid)

            update_pairs: list[tuple[int, str]] = []
            skipped_empty = 0
            mismatched: list[tuple[int, int, int]] = []
            for entry in v_entries:
                qid = entry.get("question_id")
                src_variants = entry.get("variants") or []
                if not qid or not src_variants:
                    continue
                db_ids = qid_to_variant_ids.get(qid, [])
                if len(db_ids) != len(src_variants):
                    mismatched.append((qid, len(src_variants), len(db_ids)))
                for variant_id, kk_str in zip(db_ids, src_variants):
                    if not kk_str:
                        skipped_empty += 1
                        continue
                    update_pairs.append((variant_id, kk_str))

            if update_pairs:
                ids_arr = [p[0] for p in update_pairs]
                kk_arr = [p[1] for p in update_pairs]
                conn.execute(
                    sa.text(
                        """
                        UPDATE variants
                        SET variant_text_kk = u.kk
                        FROM unnest(
                            CAST(:ids AS integer[]),
                            CAST(:kk  AS text[])
                        ) AS u(id, kk)
                        WHERE variants.id = u.id
                        """
                    ),
                    {"ids": ids_arr, "kk": kk_arr},
                )
            log.info(
                "Phase 7b rollout: variants updated=%d skipped_empty=%d mismatched_q=%d",
                len(update_pairs),
                skipped_empty,
                len(mismatched),
            )
            if mismatched:
                log.warning(
                    "Phase 7b rollout: %d questions had variant count mismatch (first 5: %s)",
                    len(mismatched),
                    mismatched[:5],
                )
    else:
        log.warning(
            "Phase 7b rollout: %s not found — Dockerfile COPY layer?",
            _V_SEED,
        )


def downgrade() -> None:
    # Best-effort: null kk for the subjects we just imported.  Math
    # rows are excluded by joining on `subject_name != 'Математика'`.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE questions q
            SET question_text_kk = NULL, hint_text_kk = NULL
            FROM subjects s
            WHERE q.subject_id = s.id AND s.name <> 'Математика'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE variants v
            SET variant_text_kk = NULL
            FROM questions q
            JOIN subjects s ON s.id = q.subject_id
            WHERE v.question_id = q.id AND s.name <> 'Математика'
            """
        )
    )
