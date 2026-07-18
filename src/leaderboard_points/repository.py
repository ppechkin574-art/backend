from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from leaderboard_points.models import LeaderboardPointsSettings
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
        interval_days: int,
        actor_display: str,
    ) -> LeaderboardPointsSettings:
        settings.auto_reset_enabled = enabled
        settings.interval_days = interval_days
        # Saving always restarts the countdown — see models.py docstring.
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
