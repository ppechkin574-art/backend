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

`sprint_prize_amount` (CRM task #19) — admin-configurable KZT prize
pool for the week's sprint winner(s). NULL means no prize is
configured (the sprint can still run purely for bragging rights).
Whole tenge, no fractional currency.
"""

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint
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
    sprint_prize_amount = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by = Column(String(200), nullable=True)


class SprintAllowedPhone(Base):
    """Admin-curated allowlist (CRM task #19): a phone number on this list
    is sprint-eligible even without an active PRO subscription (VIPs,
    testers, one-off promo grants). See `leaderboard_points.eligibility`.
    Phone numbers are stored normalized (`+7XXXXXXXXXX`, see
    `utils.validators.validate_kz_phone`)."""

    __tablename__ = "sprint_allowed_phones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(20), nullable=False, unique=True)
    added_by_display = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SprintAllowedPhone phone={self.phone_number}>"


class SprintWinner(Base):
    """One row per (week, user) that won or is awaiting tie resolution
    (CRM tasks #7 + #19).

    `resolution_type` (CRM task #19 — before this, every row was
    implicitly a "first to cross the threshold" win):
      - "threshold"   — first user to cross `sprint_target_points` this
        week (CRM #7's original behavior). At most ONE such row per week
        — enforced by the partial unique index
        `uq_sprint_winners_week_threshold` on `week_start_at` WHERE
        `resolution_type = 'threshold'`, which is what
        `try_lock_sprint_winner`'s `INSERT ... ON CONFLICT (week_start_at)
        WHERE resolution_type = 'threshold' DO NOTHING` races against.
        Concurrent callers crossing the threshold in the same week all
        attempt that INSERT; only the first commit wins the row.
      - "closest"     — nobody crossed the threshold (or no threshold is
        configured); the week ended with a single top scorer, decided by
        `LeaderboardPointsService.resolve_week_if_ended`.
      - "tie_pending" — the week ended with 2+ users tied for the top
        score; one row per tied user, `prize_share` NULL, awaiting an
        admin's `POST /admin/sprint/weeks/{week}/resolve-tie` call.
      - "tie_split"   — a `tie_pending` group after the admin resolved it;
        `prize_share` is the (possibly uneven) split of
        `sprint_prize_amount`, `resolved_by`/`resolved_at` record who/when.

    `UNIQUE(week_start_at, user_id)` (not `UNIQUE(week_start_at)` alone,
    as it was before CRM #19) — multiple winners per week are now
    possible (tie splits), so the constraint only prevents the SAME user
    from getting two rows in the same week."""

    __tablename__ = "sprint_winners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start_at = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    points_at_win = Column(Integer, nullable=False)
    won_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolution_type = Column(String(20), nullable=False, server_default="threshold")
    prize_share = Column(Integer, nullable=True)
    resolved_by = Column(String(200), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("week_start_at", "user_id", name="uq_sprint_winners_week_user"),
        Index(
            "uq_sprint_winners_week_threshold",
            "week_start_at",
            unique=True,
            postgresql_where=(resolution_type == "threshold"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SprintWinner week={self.week_start_at} user_id={self.user_id} "
            f"type={self.resolution_type}>"
        )
