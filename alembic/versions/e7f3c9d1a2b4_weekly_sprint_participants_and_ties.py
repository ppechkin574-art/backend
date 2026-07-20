"""weekly sprint: participants allowlist, card copy/prize, tie resolution

Backend for CRM task #19 ("Логика всего блока — Еженедельный спринт").
Builds on #6 (weekly reset) and #7 (threshold winner lock-in).

What changes and why:

- `leaderboard_points_settings` gains `sprint_title_ru`, `sprint_title_kk`
  and `sprint_prize_amount` — everything the mobile home card shows apart
  from the leader's own numbers. The prize lives here rather than in
  `events.prize_text` because it is also the amount split between tied
  winners and recorded per week in `sprint_winners.prize_share`; a
  free-text copy of it would be free to drift from what is paid out.

- `sprint_participants` — the admin-curated allowlist that is the only
  way into the sprint. Keyed on the phone number (not user_id) so entry
  can be granted before the payer has registered; `user_id` is
  backfilled once the phone matches a real account.

- `sprint_winners` moves from "at most one winner per week" to "at most
  one THRESHOLD winner per week, but any number of tie-split winners":
    * `UNIQUE(week_start_at)` is dropped and replaced by
      `UNIQUE(week_start_at, user_id)`,
    * a partial unique index on `week_start_at WHERE resolution_type =
      'threshold'` preserves the race-safety that the old constraint
      provided for the mid-week lock-in path,
    * `resolution_type` / `prize_share` / `resolved_by` / `resolved_at`
      record how the week was decided and what each winner is owed.
  Existing rows predate ties and are all threshold wins, so the
  `server_default` backfills them correctly with no data migration.

Revision ID: e7f3c9d1a2b4
Revises: d6e2b8a4f1c9
Create Date: 2026-07-20 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f3c9d1a2b4"
down_revision: Union[str, None] = "d6e2b8a4f1c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- card copy + prize -------------------------------------------------
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_title_ru", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_title_kk", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_prize_amount", sa.Integer(), nullable=True),
    )

    # ---- participants allowlist -------------------------------------------
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("sprint_participants"):
        op.create_table(
            "sprint_participants",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("phone_number", sa.String(length=20), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("added_by_display", sa.String(length=200), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("phone_number", name="uq_sprint_participants_phone"),
        )
        op.create_index(
            "ix_sprint_participants_user_id", "sprint_participants", ["user_id"]
        )

    # ---- winners: allow multiple per week (tie splits) --------------------
    op.add_column(
        "sprint_winners",
        sa.Column(
            "resolution_type",
            sa.String(length=20),
            nullable=False,
            server_default="threshold",
        ),
    )
    op.add_column("sprint_winners", sa.Column("prize_share", sa.Integer(), nullable=True))
    op.add_column(
        "sprint_winners", sa.Column("resolved_by", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "sprint_winners",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # The old constraint allowed exactly one winner per week, which tie
    # splits break. Drop it defensively: on a DB where #7 never landed the
    # table was created without it.
    existing = {
        c["name"] for c in sa.inspect(bind).get_unique_constraints("sprint_winners")
    }
    if "uq_sprint_winners_week_start_at" in existing:
        op.drop_constraint(
            "uq_sprint_winners_week_start_at", "sprint_winners", type_="unique"
        )

    op.create_unique_constraint(
        "uq_sprint_winners_week_user", "sprint_winners", ["week_start_at", "user_id"]
    )
    # Race-safety for the mid-week threshold lock-in, now scoped to
    # threshold rows only so tie splits are unaffected.
    op.create_index(
        "uq_sprint_winners_week_threshold",
        "sprint_winners",
        ["week_start_at"],
        unique=True,
        postgresql_where=sa.text("resolution_type = 'threshold'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sprint_winners_week_threshold", table_name="sprint_winners")
    op.drop_constraint("uq_sprint_winners_week_user", "sprint_winners", type_="unique")
    op.create_unique_constraint(
        "uq_sprint_winners_week_start_at", "sprint_winners", ["week_start_at"]
    )
    op.drop_column("sprint_winners", "resolved_at")
    op.drop_column("sprint_winners", "resolved_by")
    op.drop_column("sprint_winners", "prize_share")
    op.drop_column("sprint_winners", "resolution_type")

    op.drop_index("ix_sprint_participants_user_id", table_name="sprint_participants")
    op.drop_table("sprint_participants")

    op.drop_column("leaderboard_points_settings", "sprint_prize_amount")
    op.drop_column("leaderboard_points_settings", "sprint_title_kk")
    op.drop_column("leaderboard_points_settings", "sprint_title_ru")
