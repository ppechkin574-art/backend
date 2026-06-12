"""Add points_awarded to ent_attempts — idempotency guard for leaderboard award

Before this migration the only protection against duplicate point-award was
the `status == completed` check in EntAttemptService.answer(). Under concurrent
load (two requests for the same attempt_id arriving simultaneously) both
requests could pass the status check before either commit landed, resulting
in `add_points()` being called twice → infinite-points exploit.

This migration adds a `points_awarded` boolean column (default FALSE) that
the service flips to TRUE with an atomic `UPDATE WHERE points_awarded = FALSE
RETURNING id` (award_points_once). The UPDATE returns a row only for the
first caller; all concurrent or repeated calls get no row → skip add_points().

Safe to apply on live DB: backfilling completed attempts that already received
points is intentionally skipped — the column starts FALSE for all rows.
Re-awarding old attempts would be worse than leaving them at FALSE (they
already have the points; setting TRUE just makes future retries no-ops which
is the desired state). If exact backfill is needed, run manually:
  UPDATE ent_attempts SET points_awarded = TRUE
  WHERE status = 'completed' AND exam_type = 'full_exam' AND score > 0;

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ent_attempts",
        sa.Column(
            "points_awarded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ent_attempts", "points_awarded")
