"""partial unique index for sprint-answer idempotency

Backs the weekly-sprint per-answer scoring with a DB-level guarantee that a
given (user, question, week) can be credited at most once. `score_answer`
bakes the week into `source_id` (`"YYYY-MM-DD:question_id"`) and inserts the
`points_audit_log` row with ON CONFLICT DO NOTHING against this index, so two
concurrent identical submits can never both credit — closing the double-credit
race the pure code-side pre-check left open.

    CREATE UNIQUE INDEX uq_sprint_answer_user_source
      ON points_audit_log (user_id, source_id)
      WHERE source_type = 'sprint_answer';

Before creating it we drop any pre-existing duplicate `sprint_answer` rows
(keeping the earliest by id). Under the previous per-(attempt, question) key
duplicates shouldn't exist, but the legacy per-week key (`source_id =
"{question_id}"`, no week prefix) could repeat the same question across weeks;
deduping makes the index creation safe regardless. Only `sprint_answer` rows
are touched — every other audit source is left alone.

Both steps are guarded / idempotent (`IF NOT EXISTS`, id-based dedupe) so a
partial or repeated deploy is a no-op rather than an error.

Revision ID: f3a2c1d0e9b8
Revises: e7c1a9b4d2f0
Create Date: 2026-07-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "f3a2c1d0e9b8"
down_revision: Union[str, None] = "e7c1a9b4d2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "uq_sprint_answer_user_source"


def upgrade() -> None:
    # Drop duplicate sprint-answer rows (keep the earliest) so the unique index
    # can be built even if legacy data has repeats. Scoped to sprint_answer.
    op.execute(
        """
        DELETE FROM points_audit_log a
        USING points_audit_log b
        WHERE a.source_type = 'sprint_answer'
          AND b.source_type = 'sprint_answer'
          AND a.user_id = b.user_id
          AND a.source_id = b.source_id
          AND a.id > b.id
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX}
          ON points_audit_log (user_id, source_id)
          WHERE source_type = 'sprint_answer'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
