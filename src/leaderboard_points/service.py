from datetime import UTC, datetime, timedelta

from leaderboard_points.dtos import (
    LeaderboardPointsSettingsDTO,
    PointsAdjustResultDTO,
    PointsResetResultDTO,
)
from leaderboard_points.models import LeaderboardPointsSettings
from leaderboard_points.repository import LeaderboardPointsRepository


def _next_reset_at(settings: LeaderboardPointsSettings) -> datetime | None:
    if not settings.auto_reset_enabled or settings.last_reset_at is None:
        return None
    return settings.last_reset_at + timedelta(days=settings.interval_days)


def _to_dto(settings: LeaderboardPointsSettings) -> LeaderboardPointsSettingsDTO:
    return LeaderboardPointsSettingsDTO(
        auto_reset_enabled=settings.auto_reset_enabled,
        interval_days=settings.interval_days,
        last_reset_at=settings.last_reset_at,
        next_reset_at=_next_reset_at(settings),
        updated_at=settings.updated_at,
        updated_by=settings.updated_by,
    )


class LeaderboardPointsService:
    def __init__(self, repo: LeaderboardPointsRepository):
        self.repo = repo

    # ---------- settings ----------

    def get_settings(self) -> LeaderboardPointsSettingsDTO:
        return _to_dto(self.repo.get_or_create_settings())

    def update_settings(
        self, enabled: bool, interval_days: int, actor_display: str
    ) -> LeaderboardPointsSettingsDTO:
        settings = self.repo.get_or_create_settings()
        settings = self.repo.save_settings(settings, enabled, interval_days, actor_display)
        return _to_dto(settings)

    # ---------- single-user adjustment ----------

    def adjust_points(
        self,
        user_id,
        delta: int,
        reason: str | None,
        actor_id,
        actor_display: str,
    ) -> PointsAdjustResultDTO:
        tagged_reason = f"[{actor_display}] {reason}" if reason else f"[{actor_display}]"
        before, after = self.repo.adjust_user_points(
            user_id=user_id,
            delta=delta,
            source_type="admin_adjust",
            reason=tagged_reason,
            source_id=str(actor_id) if actor_id else None,
        )
        return PointsAdjustResultDTO(
            user_id=str(user_id),
            points_before=before,
            points_after=after,
            points_delta=after - before,
        )

    # ---------- auto-reset (called by the background scheduler) ----------

    def reset_all_points_if_due(self) -> PointsResetResultDTO:
        settings = self.repo.get_or_create_settings()
        if not settings.auto_reset_enabled:
            return PointsResetResultDTO(ran=False)

        now = datetime.now(UTC)
        due_at = (
            settings.last_reset_at + timedelta(days=settings.interval_days)
            if settings.last_reset_at
            else now
        )
        if now < due_at:
            return PointsResetResultDTO(ran=False, next_reset_at=due_at)

        reason = f"Автосброс лидерборда (интервал {settings.interval_days} дн.)"
        count = self.repo.bulk_reset_all(reason)
        settings.last_reset_at = now
        self.repo.db.flush()

        return PointsResetResultDTO(
            ran=True,
            users_reset=count,
            next_reset_at=now + timedelta(days=settings.interval_days),
        )
