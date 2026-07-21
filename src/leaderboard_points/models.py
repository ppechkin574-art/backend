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

`sprint_title_ru` / `sprint_title_kk` / `sprint_prize_amount` (CRM #19)
— everything the mobile "Еженедельный спринт" home card renders except
the leader's own numbers. Deliberately owned HERE and not in the
`events` table: the prize is also what gets split between tied winners
and recorded per week in `sprint_winners.prize_share`, so a free-text
`events.prize_text` would let the advertised prize drift away from the
one actually paid out.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database import Base

# `SprintWinner.resolution_type` — HOW this row's winner was decided.
# See the SprintWinner docstring for the full state machine.
RESOLUTION_THRESHOLD = "threshold"
RESOLUTION_CLOSEST = "closest"
RESOLUTION_TIE_PENDING = "tie_pending"
RESOLUTION_TIE_SPLIT = "tie_split"


class LeaderboardPointsSettings(Base):
    __tablename__ = "leaderboard_points_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    auto_reset_enabled = Column(Boolean, nullable=False, server_default="false")
    reset_mode = Column(String(20), nullable=False, server_default="interval")
    interval_days = Column(Integer, nullable=False, server_default="30")
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    sprint_target_points = Column(Integer, nullable=True)
    sprint_title_ru = Column(String(120), nullable=True)
    sprint_title_kk = Column(String(120), nullable=True)
    sprint_prize_amount = Column(Integer, nullable=True)
    # Where the "Купить доступ" button on the weekly-sprint screen sends a
    # non-participant (CRM #19). Entry is granted by the admin, so this is
    # just a link they control — a payment page, a WhatsApp chat, whatever.
    # NULL means the button has nowhere to go and the client hides/disables it.
    sprint_access_url = Column(String(500), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by = Column(String(200), nullable=True)


class SprintParticipant(Base):
    """Admin-curated allowlist — the ONLY way into the weekly sprint
    (CRM #19). Entry is paid outside the app (bank transfer, Kaspi…);
    the admin then adds the payer here by hand. An empty table means
    NOBODY competes this week — deliberately not "everybody competes",
    so forgetting to populate it degrades to a quiet no-op rather than
    silently entering the whole user base into a cash prize draw.

    Keyed on `phone_number` rather than `user_id` because an admin may
    grant entry *before* the payer has registered (that person has no
    Keycloak id yet). `user_id` is backfilled by
    `SprintService._resolve_participants` the first time the phone is
    matched to a real account, and stays NULL for numbers that never
    signed up. Phones are stored normalized as `+7XXXXXXXXXX`."""

    __tablename__ = "sprint_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(20), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    added_by_display = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SprintParticipant phone={self.phone_number}>"


class SprintRankSnapshot(Base):
    """A participant's rank at a point in time, so the weekly-standings
    screen can show a "moved up/down N places" badge (CRM #19).

    Movement is measured against the START OF THE CURRENT DAY: a background
    job records one snapshot per participant at ~00:00 Asia/Almaty, and the
    standings endpoint diffs today's live rank against it, so the badge
    reads "how you moved today". Without a stored snapshot there is nothing
    to diff, so on the first day of a week (no prior snapshot) badges are
    simply absent rather than wrong.

    `(week_start_at, captured_for_day, user_id)` is unique — one row per
    participant per day. `captured_for_day` is the Almaty date the snapshot
    represents, stored as that day's 00:00 in UTC."""

    __tablename__ = "sprint_rank_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start_at = Column(DateTime(timezone=True), nullable=False)
    captured_for_day = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    rank = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "week_start_at",
            "captured_for_day",
            "user_id",
            name="uq_sprint_rank_snapshot",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SprintRankSnapshot day={self.captured_for_day} "
            f"user_id={self.user_id} rank={self.rank}>"
        )


class SprintWinner(Base):
    """One row per (week, winner). `week_start_at` is the Monday 00:00
    Asia/Almaty identifying the week — see `current_week_start_almaty`.

    `resolution_type` records HOW the row was decided:

    - `threshold`   — someone crossed `sprint_target_points` mid-week and
      won early (CRM #7's original behaviour). At most ONE per week,
      enforced by the partial unique index `uq_sprint_winners_week_threshold`.
      That index is what `try_lock_sprint_winner`'s
      `INSERT … ON CONFLICT DO NOTHING` races against: concurrent
      crossings all attempt the insert, only the first commit gets the row.
    - `closest`     — nobody crossed (or no threshold configured) and the
      week ended with a single top scorer. Written by `close_week_if_due`.
    - `tie_pending` — the week ended with 2+ users tied at the top. One row
      per tied user, `prize_share` NULL, waiting for an admin to call
      `POST /admin/sprint/weeks/{week}/resolve-tie`.
    - `tie_split`   — a `tie_pending` group after the admin resolved it;
      `prize_share` holds each winner's cut of `sprint_prize_amount`.

    UNIQUE is `(week_start_at, user_id)` and not `week_start_at` alone,
    because tie splits legitimately produce several winners per week; the
    constraint only stops the SAME user being recorded twice in one week.

    A locked-in row is never revoked: deleting the participant, banning
    the user or editing the prize afterwards leaves history untouched —
    `prize_share` is the amount owed as of resolution time."""

    __tablename__ = "sprint_winners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start_at = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    points_at_win = Column(Integer, nullable=False)
    won_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolution_type = Column(
        String(20), nullable=False, server_default=RESOLUTION_THRESHOLD
    )
    prize_share = Column(Integer, nullable=True)
    resolved_by = Column(String(200), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("week_start_at", "user_id", name="uq_sprint_winners_week_user"),
        Index(
            "uq_sprint_winners_week_threshold",
            "week_start_at",
            unique=True,
            postgresql_where=Column("resolution_type") == RESOLUTION_THRESHOLD,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SprintWinner week={self.week_start_at} user_id={self.user_id} "
            f"type={self.resolution_type}>"
        )
