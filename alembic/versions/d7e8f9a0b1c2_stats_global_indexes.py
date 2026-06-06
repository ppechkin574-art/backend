"""add composite indexes for /user/statistics/global hot paths

Speeds up the enhanced global-statistics endpoint, which runs ~16 sequential
aggregation queries over the attempt tables. The added indexes match the
endpoint's real WHERE / JOIN columns:

  ent_attempts
    - (student_guid, exam_type, completed_at)  → overall ENT stats
      (get_all_completed_attempts / get_attempt_subjects_statistics filter
       student_guid + exam_type + status==completed)
    - (student_guid, status, completed_at)     → period ENT stats
      (get_completed_attempts_by_period: student_guid + status + completed_at
       range; the period helper does not filter exam_type, so a status-led
       index serves it) and the full-ENT 365-day history query.

  ent_attempt_answers
    - (ent_attempt_id)                         → per-attempt answer fetch in
      the stats loop + the subjects-statistics join (FK was unindexed).

  trainer_attempts
    - (student_guid, status, completed_at)     → both period and overall
      trainer stats filter student_guid + status==completed (+ range).

  trainer_attempt_questions
    - (trainer_attempt_id)                     → per-attempt relationship load
      + overall subject/topic join (FK was unindexed).

  trainer_attempt_answers
    - (trainer_attempt_question_id)            → overall subject/topic join
      (FK was unindexed).

  daily_test_attempts
    - (student_guid, status, completed_at)     → period + overall daily stats.
      The pre-existing idx_daily_attempts_student is student-only and cannot
      satisfy the status / completed_at-range predicate.

Daily FK indexes (idx_daily_attempt_questions_attempt,
idx_daily_answers_attempt) already exist, so no FK indexes are added there.

LOCK NOTE: plain `CREATE INDEX` (what op.create_index emits) takes a brief
SHARE lock that blocks writes to the table for the duration of the build. The
attempt tables can be large, so if this migration is run against a hot prod DB
a follow-up could switch these to `CREATE INDEX CONCURRENTLY` via op.execute()
under an autocommit block (CONCURRENTLY cannot run inside a transaction). Kept
as standard create_index here for a single, reviewable, reversible migration.

Revision ID: d7e8f9a0b1c2
Revises: c2a3b4d5e6f7
Create Date: 2026-06-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c2a3b4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ent_attempts
    op.create_index(
        "ix_ent_attempts_student_examtype_completed",
        "ent_attempts",
        ["student_guid", "exam_type", "completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_ent_attempts_student_status_completed",
        "ent_attempts",
        ["student_guid", "status", "completed_at"],
        unique=False,
    )

    # ent_attempt_answers (FK)
    op.create_index(
        "ix_ent_attempt_answers_attempt",
        "ent_attempt_answers",
        ["ent_attempt_id"],
        unique=False,
    )

    # trainer_attempts
    op.create_index(
        "ix_trainer_attempts_student_status_completed",
        "trainer_attempts",
        ["student_guid", "status", "completed_at"],
        unique=False,
    )

    # trainer_attempt_questions (FK)
    op.create_index(
        "ix_trainer_attempt_questions_attempt",
        "trainer_attempt_questions",
        ["trainer_attempt_id"],
        unique=False,
    )

    # trainer_attempt_answers (FK)
    op.create_index(
        "ix_trainer_attempt_answers_question",
        "trainer_attempt_answers",
        ["trainer_attempt_question_id"],
        unique=False,
    )

    # daily_test_attempts
    op.create_index(
        "ix_daily_attempts_student_status_completed",
        "daily_test_attempts",
        ["student_guid", "status", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_attempts_student_status_completed", table_name="daily_test_attempts")
    op.drop_index("ix_trainer_attempt_answers_question", table_name="trainer_attempt_answers")
    op.drop_index("ix_trainer_attempt_questions_attempt", table_name="trainer_attempt_questions")
    op.drop_index("ix_trainer_attempts_student_status_completed", table_name="trainer_attempts")
    op.drop_index("ix_ent_attempt_answers_attempt", table_name="ent_attempt_answers")
    op.drop_index("ix_ent_attempts_student_status_completed", table_name="ent_attempts")
    op.drop_index("ix_ent_attempts_student_examtype_completed", table_name="ent_attempts")
