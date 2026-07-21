from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from leaderboard_points.models import (
    RESOLUTION_THRESHOLD,
    RESOLUTION_TIE_PENDING,
    RESOLUTION_TIE_SPLIT,
    LeaderboardPointsSettings,
    SprintParticipant,
    SprintRankSnapshot,
    SprintWinner,
)
from quiz.models.user_points import UserPoints


class LeaderboardPointsRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------- settings (singleton row) ----------

    def get_or_create_settings(self) -> LeaderboardPointsSettings:
        settings = self.db.query(LeaderboardPointsSettings).order_by(
            LeaderboardPointsSettings.id
        ).first()
        if settings is None:
            settings = LeaderboardPointsSettings()
            self.db.add(settings)
            self.db.flush()
        return settings

    # Columns an admin PATCH is allowed to write. Anything else in the
    # payload is ignored rather than blindly setattr'd onto the model.
    _SETTINGS_WRITABLE = frozenset(
        {
            "auto_reset_enabled",
            "reset_mode",
            "interval_days",
            "sprint_target_points",
            "sprint_title_ru",
            "sprint_title_kk",
            "sprint_prize_amount",
        }
    )
    # Changing any of these restarts the auto-reset countdown; the sprint
    # copy/prize fields do not, so editing the card text must not silently
    # postpone the next points reset.
    _RESET_COUNTDOWN_FIELDS = frozenset(
        {"auto_reset_enabled", "reset_mode", "interval_days"}
    )

    def save_settings(
        self,
        settings: LeaderboardPointsSettings,
        changes: dict,
        actor_display: str,
    ) -> LeaderboardPointsSettings:
        """Partial write — see `LeaderboardPointsService.update_settings`
        for why this is not a full overwrite."""
        applied = {k: v for k, v in changes.items() if k in self._SETTINGS_WRITABLE}
        for field, value in applied.items():
            setattr(settings, field, value)
        if self._RESET_COUNTDOWN_FIELDS & applied.keys():
            # Saving the cadence always restarts the countdown — see the
            # models.py docstring.
            settings.last_reset_at = datetime.now(UTC)
        settings.updated_by = actor_display
        self.db.flush()
        return settings

    # ---------- single-user adjustment ----------

    def adjust_user_points(
        self,
        user_id,
        delta: int,
        source_type: str,
        reason: str | None,
        source_id: str | None = None,
    ) -> tuple[int, int]:
        """Atomically applies `delta`, clamped so the total never drops
        below 0, and writes an audit-log row. Returns (points_before, points_after)."""
        from security.models import PointsAuditLog

        points_before = (
            self.db.query(UserPoints.total_points)
            .filter(UserPoints.user_id == user_id)
            .scalar()
        ) or 0

        row = self.db.execute(
            text("""
                INSERT INTO user_points (user_id, total_points)
                VALUES (:user_id, GREATEST(0, :delta))
                ON CONFLICT (user_id) DO UPDATE
                SET total_points = GREATEST(0, user_points.total_points + :delta)
                RETURNING total_points
            """),
            {"user_id": user_id, "delta": delta},
        ).first()
        points_after = row[0]
        actual_delta = points_after - points_before

        self.db.add(
            PointsAuditLog(
                user_id=user_id,
                points_before=points_before,
                points_after=points_after,
                points_delta=actual_delta,
                source_type=source_type,
                source_id=source_id,
                reason=reason,
                is_suspicious=False,
            )
        )
        self.db.flush()
        return points_before, points_after

    # ---------- bulk reset (auto-reset job) ----------

    def bulk_reset_all(self, reason: str) -> int:
        """Zeroes total_points for every user with a nonzero balance
        (hidden users included — reset is global by design), logging one
        audit row per affected user. Returns the number of users reset."""
        from security.models import PointsAuditLog

        rows = self.db.execute(
            text("SELECT user_id, total_points FROM user_points WHERE total_points <> 0")
        ).all()
        if not rows:
            return 0

        now = datetime.now(UTC)
        self.db.bulk_save_objects(
            [
                PointsAuditLog(
                    user_id=user_id,
                    points_before=total_points,
                    points_after=0,
                    points_delta=-total_points,
                    source_type="auto_reset",
                    source_id=None,
                    reason=reason,
                    is_suspicious=False,
                    created_at=now,
                )
                for user_id, total_points in rows
            ]
        )
        self.db.execute(text("UPDATE user_points SET total_points = 0 WHERE total_points <> 0"))
        self.db.flush()
        return len(rows)

    # ---------- sprint winner (CRM task #7) ----------

    def try_lock_sprint_winner(
        self, week_start_at: datetime, user_id: UUID, points_at_win: int
    ) -> bool:
        """Attempt to lock `user_id` in as the THRESHOLD winner of the
        sprint week identified by `week_start_at`. Concurrency-safe: the
        partial unique index `uq_sprint_winners_week_threshold`
        (`week_start_at WHERE resolution_type = 'threshold'`) means only
        the first concurrent INSERT for a given week actually lands —
        every other racing call's INSERT is a silent no-op (`ON CONFLICT
        DO NOTHING`), so at most one early winner ever exists per week
        regardless of how many requests cross the threshold at the same
        instant. The index is partial so that end-of-week tie splits,
        which legitimately write several rows for one week, are not
        blocked by it.

        Returns True only when THIS call is the one that won the lock
        (a row was returned AND its user_id matches the caller's). A
        conflict (no row returned) or a row belonging to a different
        user (a previous winning call already claimed the week) both
        return False."""
        row = self.db.execute(
            text("""
                INSERT INTO sprint_winners
                    (week_start_at, user_id, points_at_win, resolution_type)
                VALUES (:week_start_at, :user_id, :points_at_win, 'threshold')
                ON CONFLICT (week_start_at) WHERE resolution_type = 'threshold'
                DO NOTHING
                RETURNING user_id
            """),
            {
                "week_start_at": week_start_at,
                "user_id": user_id,
                "points_at_win": points_at_win,
            },
        ).first()
        if row is None:
            return False
        return str(row[0]) == str(user_id)

    def get_current_sprint_winner_row(
        self, week_start_at: datetime
    ) -> tuple[UUID, int, datetime] | None:
        """Raw (user_id, points_at_win, won_at) of the THRESHOLD winner for
        the sprint week identified by `week_start_at`, or None if nobody has
        reached the target yet this week. Restricted to threshold rows on
        purpose: end-of-week `closest`/`tie_*` rows describe a week that is
        already over, whereas every caller of this method is asking "has
        this week been won early?". Deliberately returns the raw row
        rather than a fully-resolved DTO — resolving the winner's
        display name/avatar needs the same Keycloak/cache/user_display
        lookup chain `GET /leaderboard` already uses (idp client,
        CacheService, UserDisplayRepository), which lives at the API
        route layer, not here. The route composes this row with that
        existing `_resolve_display` mechanism instead of a second one."""
        row = (
            self.db.query(
                SprintWinner.user_id, SprintWinner.points_at_win, SprintWinner.won_at
            )
            .filter(
                SprintWinner.week_start_at == week_start_at,
                SprintWinner.resolution_type == RESOLUTION_THRESHOLD,
            )
            .first()
        )
        if row is None:
            return None
        return (row[0], row[1], row[2])

    # ---------- weekly standings (CRM #19) ----------

    def weekly_points(
        self,
        week_start_at: datetime,
        week_end_at: datetime,
        user_ids: list[UUID],
    ) -> list[tuple[UUID, int, datetime]]:
        """Sum of `points_delta` inside the week window, per participant,
        best first. Returns (user_id, points, last_scored_at).

        This — not `user_points.total_points` — is what "points this week"
        means for the sprint. Deriving it from the audit log keeps the
        all-time "Кубок" rating (`total_points`) completely untouched, so
        the two leaderboards can coexist without one resetting the other.

        Excludes `auto_reset` rows: those are the bookkeeping entries the
        global reset job writes (a negative delta cancelling a balance),
        not points anybody won or lost by playing. Rows are dropped once
        the participant's net for the week is <= 0, so a purely negative
        admin correction cannot put someone on the board.

        Ordering is by points desc, then by `last_scored_at` asc — whoever
        reached the score first ranks higher. That only decides DISPLAY
        order; an actual tie at the top is resolved by an admin, never
        silently by this ordering (see `close_week`)."""
        if not user_ids:
            return []

        rows = self.db.execute(
            text("""
                SELECT user_id,
                       SUM(points_delta)  AS points,
                       MAX(created_at)    AS last_scored_at
                FROM points_audit_log
                WHERE created_at >= :week_start
                  AND created_at <  :week_end
                  AND source_type <> 'auto_reset'
                  AND user_id = ANY(:user_ids)
                GROUP BY user_id
                HAVING SUM(points_delta) > 0
                ORDER BY points DESC, last_scored_at ASC
            """),
            {
                "week_start": week_start_at,
                "week_end": week_end_at,
                "user_ids": user_ids,
            },
        ).all()
        return [(r[0], int(r[1]), r[2]) for r in rows]

    # ---------- participants allowlist (CRM #19) ----------

    def list_participants(self) -> list[SprintParticipant]:
        return (
            self.db.query(SprintParticipant)
            .order_by(SprintParticipant.created_at.desc())
            .all()
        )

    def participant_user_ids(self) -> list[UUID]:
        """User ids of allowlisted people who actually have an account.
        Entries still awaiting registration (`user_id IS NULL`) simply do
        not appear — they cannot score points yet anyway."""
        rows = (
            self.db.query(SprintParticipant.user_id)
            .filter(SprintParticipant.user_id.is_not(None))
            .all()
        )
        return [r[0] for r in rows]

    def count_participants(self) -> int:
        """Size of the whole allowlist, including entries granted in
        advance to phones with no account yet — this is the "из N" the
        mobile card shows, i.e. how many people paid to compete."""
        return self.db.query(SprintParticipant).count()

    def get_participant_by_phone(self, phone_number: str) -> SprintParticipant | None:
        return (
            self.db.query(SprintParticipant)
            .filter(SprintParticipant.phone_number == phone_number)
            .first()
        )

    def add_participant(
        self, phone_number: str, user_id: UUID | None, added_by_display: str
    ) -> SprintParticipant:
        participant = SprintParticipant(
            phone_number=phone_number,
            user_id=user_id,
            added_by_display=added_by_display,
        )
        self.db.add(participant)
        self.db.flush()
        return participant

    def set_participant_user_id(self, participant_id: int, user_id: UUID) -> None:
        """Backfill after a phone granted entry in advance finally signs up."""
        self.db.query(SprintParticipant).filter(
            SprintParticipant.id == participant_id
        ).update({"user_id": user_id})
        self.db.flush()

    def delete_participant(self, participant_id: int) -> bool:
        deleted = (
            self.db.query(SprintParticipant)
            .filter(SprintParticipant.id == participant_id)
            .delete()
        )
        self.db.flush()
        return bool(deleted)

    # ---------- winners: week close, history, tie resolution ----------

    def list_winners_for_week(self, week_start_at: datetime) -> list[SprintWinner]:
        return (
            self.db.query(SprintWinner)
            .filter(SprintWinner.week_start_at == week_start_at)
            .order_by(SprintWinner.points_at_win.desc())
            .all()
        )

    def list_winners_history(self, limit: int = 100) -> list[SprintWinner]:
        return (
            self.db.query(SprintWinner)
            .order_by(SprintWinner.week_start_at.desc(), SprintWinner.points_at_win.desc())
            .limit(limit)
            .all()
        )

    def week_has_winner(self, week_start_at: datetime) -> bool:
        """True once ANY row exists for the week — the guard that stops the
        week-close job from resolving the same week twice."""
        return (
            self.db.query(SprintWinner.id)
            .filter(SprintWinner.week_start_at == week_start_at)
            .first()
            is not None
        )

    def record_week_winners(
        self,
        week_start_at: datetime,
        entries: list[tuple[UUID, int]],
        resolution_type: str,
        prize_share: int | None,
    ) -> int:
        """Write the end-of-week outcome: one row for `closest`, several for
        `tie_pending`. Idempotent by way of `UNIQUE(week_start_at, user_id)`
        — a duplicate run inserts nothing rather than doubling the history."""
        if not entries:
            return 0
        for user_id, points in entries:
            self.db.execute(
                text("""
                    INSERT INTO sprint_winners
                        (week_start_at, user_id, points_at_win,
                         resolution_type, prize_share)
                    VALUES (:week, :user_id, :points, :rtype, :share)
                    ON CONFLICT (week_start_at, user_id) DO NOTHING
                """),
                {
                    "week": week_start_at,
                    "user_id": user_id,
                    "points": points,
                    "rtype": resolution_type,
                    "share": prize_share,
                },
            )
        self.db.flush()
        return len(entries)

    def resolve_tie(
        self, week_start_at: datetime, prize_share: int | None, resolved_by: str
    ) -> int:
        """Flip a week's `tie_pending` rows to `tie_split`, stamping each
        winner's cut. Returns how many rows were affected (0 when the week
        has no pending tie — the caller turns that into a 404/409)."""
        affected = (
            self.db.query(SprintWinner)
            .filter(
                SprintWinner.week_start_at == week_start_at,
                SprintWinner.resolution_type == RESOLUTION_TIE_PENDING,
            )
            .update(
                {
                    "resolution_type": RESOLUTION_TIE_SPLIT,
                    "prize_share": prize_share,
                    "resolved_by": resolved_by,
                    "resolved_at": datetime.now(UTC),
                },
                synchronize_session=False,
            )
        )
        self.db.flush()
        return affected

    # ---------- daily rank snapshots (movement badge, CRM #19) ----------

    def latest_snapshot_ranks(
        self, week_start_at: datetime, before_day: datetime
    ) -> dict[UUID, int]:
        """user_id → rank from the most recent snapshot day STRICTLY BEFORE
        `before_day`, for the given week. `before_day` is today's 00:00
        Almaty, so this returns yesterday's (or the latest earlier day's)
        ranks — the baseline the movement badge diffs against.

        Returns {} when the week has no earlier snapshot yet (its first
        day): the standings endpoint then emits no badges rather than
        pretending everyone is unchanged."""
        latest_day = (
            self.db.query(func.max(SprintRankSnapshot.captured_for_day))
            .filter(
                SprintRankSnapshot.week_start_at == week_start_at,
                SprintRankSnapshot.captured_for_day < before_day,
            )
            .scalar()
        )
        if latest_day is None:
            return {}
        rows = (
            self.db.query(SprintRankSnapshot.user_id, SprintRankSnapshot.rank)
            .filter(
                SprintRankSnapshot.week_start_at == week_start_at,
                SprintRankSnapshot.captured_for_day == latest_day,
            )
            .all()
        )
        return {r[0]: r[1] for r in rows}

    def save_rank_snapshot(
        self,
        week_start_at: datetime,
        captured_for_day: datetime,
        ranks: list[tuple[UUID, int]],
    ) -> int:
        """Write today's rank snapshot, one row per participant. Idempotent
        via `uq_sprint_rank_snapshot` — a same-day re-run refreshes each
        row's rank instead of duplicating, so running the job hourly is
        safe even though it only needs to land once a day."""
        if not ranks:
            return 0
        for user_id, rank in ranks:
            self.db.execute(
                text("""
                    INSERT INTO sprint_rank_snapshots
                        (week_start_at, captured_for_day, user_id, rank)
                    VALUES (:week, :day, :user_id, :rank)
                    ON CONFLICT (week_start_at, captured_for_day, user_id)
                    DO UPDATE SET rank = EXCLUDED.rank
                """),
                {
                    "week": week_start_at,
                    "day": captured_for_day,
                    "user_id": user_id,
                    "rank": rank,
                },
            )
        self.db.flush()
        return len(ranks)

    def snapshot_exists_for_day(
        self, week_start_at: datetime, captured_for_day: datetime
    ) -> bool:
        return (
            self.db.query(SprintRankSnapshot.id)
            .filter(
                SprintRankSnapshot.week_start_at == week_start_at,
                SprintRankSnapshot.captured_for_day == captured_for_day,
            )
            .first()
            is not None
        )
