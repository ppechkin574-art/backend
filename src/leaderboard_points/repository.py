from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from leaderboard_points.models import LeaderboardPointsSettings, SprintWinner
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

    def save_settings(
        self,
        settings: LeaderboardPointsSettings,
        enabled: bool,
        reset_mode: str,
        interval_days: int,
        actor_display: str,
        sprint_target_points: int | None = None,
    ) -> LeaderboardPointsSettings:
        settings.auto_reset_enabled = enabled
        settings.reset_mode = reset_mode
        settings.interval_days = interval_days
        # Saving always restarts the countdown — see models.py docstring.
        settings.last_reset_at = datetime.now(UTC)
        settings.sprint_target_points = sprint_target_points
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
        """Attempt to lock `user_id` in as the winner of the sprint week
        identified by `week_start_at`. Concurrency-safe: the UNIQUE
        constraint on `sprint_winners.week_start_at` means only the
        first concurrent INSERT for a given week actually lands — every
        other racing call's INSERT is a silent no-op (`ON CONFLICT DO
        NOTHING`), so at most one row (and one winner) ever exists per
        week regardless of how many requests cross the threshold at
        the same instant.

        Returns True only when THIS call is the one that won the lock
        (a row was returned AND its user_id matches the caller's). A
        conflict (no row returned) or a row belonging to a different
        user (a previous winning call already claimed the week) both
        return False."""
        row = self.db.execute(
            text("""
                INSERT INTO sprint_winners (week_start_at, user_id, points_at_win)
                VALUES (:week_start_at, :user_id, :points_at_win)
                ON CONFLICT (week_start_at) DO NOTHING
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
        """Raw (user_id, points_at_win, won_at) for the sprint week
        identified by `week_start_at`, or None if nobody has reached
        the target yet this week. Deliberately returns the raw row
        rather than a fully-resolved DTO — resolving the winner's
        display name/avatar needs the same Keycloak/cache/user_display
        lookup chain `GET /leaderboard` already uses (idp client,
        CacheService, UserDisplayRepository), which lives at the API
        route layer, not here. The route composes this row with that
        existing `_resolve_display` mechanism instead of a second one."""
        row = self.db.query(
            SprintWinner.user_id, SprintWinner.points_at_win, SprintWinner.won_at
        ).filter(SprintWinner.week_start_at == week_start_at).first()
        if row is None:
            return None
        return (row[0], row[1], row[2])
