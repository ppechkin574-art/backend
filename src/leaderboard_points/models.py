"""Admin-configurable auto-reset schedule for leaderboard points.

Singleton table (always exactly one row, id=1) — same shape as other
single-row config tables in this codebase (see app_config). Saving the
settings from the admin panel always restarts the countdown from "now":
`last_reset_at` is stamped on every `update_settings` call, so
`next_reset_at = last_reset_at + interval_days` is simple to compute
and never surprises the operator with a reset older config would have
already triggered.

`reset_mode` picks how `next_reset_at` is computed:
- `"interval"` (default, backward-compatible) — `last_reset_at + interval_days`.
- `"weekly_monday"` — the next Monday 00:00 Asia/Almaty strictly after
  `last_reset_at`. Added for the "Еженедельный спринт" requirement
  (CRM task #6): points must reset every Monday at midnight, not on an
  arbitrary N-day cadence. `interval_days` is ignored in this mode but
  kept populated (not nulled) so switching back to "interval" restores
  the previous cadence without the operator re-entering it.

`sprint_target_points` (CRM task #7) — admin-configurable points
threshold for the "first to reach N points this week wins the sprint"
rule. NULL/0 means the feature is off: `LeaderboardPointsService.
check_and_lock_sprint_winner` no-ops and no `SprintWinner` rows are
ever created. Independent of `reset_mode`/`auto_reset_enabled` — the
sprint winner is locked in off the calendar week (see
`current_week_start_almaty`), not off whatever the points-reset
schedule happens to be, so the feature works even before/without
weekly auto-reset being turned on.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database import Base


class LeaderboardPointsSettings(Base):
    __tablename__ = "leaderboard_points_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    auto_reset_enabled = Column(Boolean, nullable=False, server_default="false")
    reset_mode = Column(String(20), nullable=False, server_default="interval")
    interval_days = Column(Integer, nullable=False, server_default="30")
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    sprint_target_points = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by = Column(String(200), nullable=True)


class SprintWinner(Base):
    """One row per week that had a winner (CRM task #7). `week_start_at`
    (the Monday 00:00 Asia/Almaty identifying the week — see
    `current_week_start_almaty`) is UNIQUE: that constraint is the
    concurrency-safety mechanism. Multiple requests racing to be the
    first to cross `sprint_target_points` in the same week all attempt
    `INSERT ... ON CONFLICT (week_start_at) DO NOTHING RETURNING
    user_id`; only the first commit wins the row, everyone else's
    INSERT is a no-op. See `LeaderboardPointsRepository.
    try_lock_sprint_winner`."""

    __tablename__ = "sprint_winners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start_at = Column(DateTime(timezone=True), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    points_at_win = Column(Integer, nullable=False)
    won_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SprintWinner week={self.week_start_at} user_id={self.user_id}>"
