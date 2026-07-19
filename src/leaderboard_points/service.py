from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from leaderboard_points.dtos import (
    LeaderboardPointsSettingsDTO,
    PointsAdjustResultDTO,
    PointsResetResultDTO,
)
from leaderboard_points.models import LeaderboardPointsSettings
from leaderboard_points.repository import LeaderboardPointsRepository

ALMATY_TZ = ZoneInfo("Asia/Almaty")
WEEKLY_MONDAY = "weekly_monday"


def next_monday_midnight_almaty(after: datetime) -> datetime:
    """The next Monday 00:00 Asia/Almaty strictly after `after`, returned
    as a UTC-aware datetime. Almaty has no DST, so this is a plain
    fixed UTC+5 conversion — no ambiguous/skipped local times to guard
    against."""
    local = after.astimezone(ALMATY_TZ)
    days_ahead = (7 - local.weekday()) % 7  # Monday == 0
    candidate = (local + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


def _next_reset_at(settings: LeaderboardPointsSettings) -> datetime | None:
    if not settings.auto_reset_enabled or settings.last_reset_at is None:
        return None
    if settings.reset_mode == WEEKLY_MONDAY:
        return next_monday_midnight_almaty(settings.last_reset_at)
    return settings.last_reset_at + timedelta(days=settings.interval_days)


def _to_dto(settings: LeaderboardPointsSettings) -> LeaderboardPointsSettingsDTO:
    return LeaderboardPointsSettingsDTO(
        auto_reset_enabled=settings.auto_reset_enabled,
        reset_mode=settings.reset_mode,
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
        self,
        enabled: bool,
        reset_mode: str,
        interval_days: int,
        actor_display: str,
    ) -> LeaderboardPointsSettingsDTO:
        settings = self.repo.get_or_create_settings()
        settings = self.repo.save_settings(
            settings, enabled, reset_mode, interval_days, actor_display
        )
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

        is_weekly = settings.reset_mode == WEEKLY_MONDAY
        now = datetime.now(UTC)
        if settings.last_reset_at is None:
            due_at = now
        elif is_weekly:
            due_at = next_monday_midnight_almaty(settings.last_reset_at)
        else:
            due_at = settings.last_reset_at + timedelta(days=settings.interval_days)

        if now < due_at:
            return PointsResetResultDTO(ran=False, next_reset_at=due_at)

        reason = (
            "Автосброс лидерборда (еженедельный спринт, понедельник 00:00 Алматы)"
            if is_weekly
            else f"Автосброс лидерборда (интервал {settings.interval_days} дн.)"
        )
        count = self.repo.bulk_reset_all(reason)
        settings.last_reset_at = now
        self.repo.db.flush()

        next_reset_at = (
            next_monday_midnight_almaty(now)
            if is_weekly
            else now + timedelta(days=settings.interval_days)
        )
        return PointsResetResultDTO(
            ran=True,
            users_reset=count,
            next_reset_at=next_reset_at,
        )
