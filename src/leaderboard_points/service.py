import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from leaderboard_points.dtos import (
    LeaderboardPointsSettingsDTO,
    PointsAdjustResultDTO,
    PointsResetResultDTO,
)
from leaderboard_points.models import LeaderboardPointsSettings
from leaderboard_points.repository import LeaderboardPointsRepository

logger = logging.getLogger(__name__)

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


def current_week_start_almaty(now: datetime) -> datetime:
    """The most recent Monday 00:00 Asia/Almaty at-or-before `now`,
    returned as a UTC-aware datetime. Almaty has no DST, so — like
    `next_monday_midnight_almaty` above — this is a plain fixed UTC+5
    conversion, no ambiguous/skipped local times to guard against.

    Pure calendar function for CRM task #7 ("Еженедельный спринт"
    winner lock-in): deliberately does NOT read `settings.reset_mode`
    or `settings.last_reset_at`. "This week" for the sprint-winner
    feature is defined by the calendar, not by whatever the points
    auto-reset schedule (CRM task #6) happens to be configured to —
    so locking in a winner works correctly even if weekly auto-reset
    is disabled or still set to "interval" mode."""
    local = now.astimezone(ALMATY_TZ)
    candidate = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return candidate.astimezone(UTC)


def current_week_bounds_almaty(now: datetime) -> tuple[datetime, datetime]:
    """`[Monday 00:00, next Monday 00:00)` around `now`, Asia/Almaty, as
    UTC-aware datetimes. Half-open on purpose: the end bound doubles as the
    next week's start, so a point scored at 23:59:59.999 on Sunday lands in
    exactly one week and none is double-counted at the boundary.

    The mobile card's "Закончится через" countdown is this end bound minus
    now, computed against Almaty rather than the phone's timezone — a user
    on Moscow time must see the same deadline as everyone else."""
    start = current_week_start_almaty(now)
    return start, start + timedelta(days=7)


def current_day_start_almaty(now: datetime) -> datetime:
    """Today's 00:00 Asia/Almaty as a UTC-aware datetime. Used to stamp the
    daily rank snapshot the movement badge diffs against."""
    local = now.astimezone(ALMATY_TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day.astimezone(UTC)


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
        sprint_target_points=settings.sprint_target_points,
        sprint_title_ru=settings.sprint_title_ru,
        sprint_title_kk=settings.sprint_title_kk,
        sprint_prize_amount=settings.sprint_prize_amount,
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
        changes: dict,
        actor_display: str,
    ) -> LeaderboardPointsSettingsDTO:
        """Applies only the keys present in `changes` (the caller passes
        `model_dump(exclude_unset=True)`), leaving every other column alone.

        Partial on purpose: two admin screens PATCH this same row — the
        Users page owns the auto-reset cadence, Tournament→Sprint owns the
        threshold, prize and card copy. With a full overwrite, saving one
        page would silently reset the other page's fields to their
        defaults. An explicit `null` in the payload IS applied, since
        that is how the admin clears the threshold or the prize."""
        settings = self.repo.get_or_create_settings()
        settings = self.repo.save_settings(settings, changes, actor_display)
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
        # Manual adjustments bypass `UserPointsRepository.add_points`, which
        # is where the sprint-winner hook normally fires. Without this call an
        # admin could hand a participant enough points to clear the weekly
        # threshold and no winner would ever be locked in — the award would
        # silently not count towards the sprint it visibly should.
        self.check_and_lock_sprint_winner(user_id, after)
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

    # ---------- sprint winner (CRM task #7) ----------

    def check_and_lock_sprint_winner(self, user_id: UUID, total_points_after: int) -> None:
        """Side-effect hook: called after every points award (ЕНТ full-exam
        completion, battle win, referral/payment reward — see
        `UserPointsRepository.add_points`). Locks `user_id` in as this
        week's "Еженедельный спринт" winner the first time their points
        EARNED THIS WEEK cross the admin-configured threshold.

        `total_points_after` is the caller's new all-time balance and is
        deliberately NOT what gets compared: the sprint runs on points
        earned inside the current week, summed from `points_audit_log`,
        while `total_points` keeps accumulating forever for the separate
        "Кубок" rating. Comparing the all-time total would hand week 2's
        prize to whoever happened to be ahead overall. The argument is
        kept in the signature because it is a free short-circuit — a user
        whose lifetime total is below the threshold cannot possibly be
        above it for a single week, so we skip the aggregate query.

        No-ops entirely when the feature is off (`sprint_target_points`
        is None/0), when the user is not on the admin allowlist (entry is
        paid for; non-participants earn points normally, they just cannot
        win the prize), or when the user is on the leaderboard hide-list —
        same exclusion `GET /leaderboard` already applies, a hidden user
        shouldn't headline the public sprint banner either.

        MUST NEVER RAISE: this runs inline in the hot points-award path
        used by quiz/battle/exam completion — a bug here must not break
        the caller's actual points award.

        Runs inside a SAVEPOINT (`db.begin_nested()`), not just a bare
        try/except — same pattern as `battle/service.py`'s
        `_add_to_user_points`/`_credit_stars_to_bank` ("Use a savepoint
        so a failure here doesn't corrupt the outer transaction."). This
        matters concretely for a deploy-ordering edge case: Railway's
        auto-deploy does not guarantee the Alembic migration for
        `sprint_target_points`/`sprint_winners` has run before the new
        backend code is live, so `get_or_create_settings()` or
        `try_lock_sprint_winner()` can hit Postgres errors (missing
        column/table) during that window. A raw Postgres error aborts
        the whole transaction — a bare `except Exception: log` catches
        the Python exception but does NOT un-abort the transaction, so
        the caller's subsequent `commit()` (e.g. `EntAttemptService.
        answer()`'s `self._uow.commit()`, needed right after for the
        cashback check) would then raise, unhandled, breaking exam
        completion. `ROLLBACK TO SAVEPOINT` (issued by begin_nested()'s
        context manager when it observes the exception) undoes exactly
        that abort, so the outer transaction — and the points award
        that already happened in it — stays healthy."""
        try:
            with self.repo.db.begin_nested():
                settings = self.repo.get_or_create_settings()
                target = settings.sprint_target_points
                if not target:
                    return
                # Cheap upper bound: this week's points can never exceed the
                # all-time total, so a total below target rules the user out
                # without touching points_audit_log.
                if total_points_after < target:
                    return

                if user_id not in self.repo.participant_user_ids():
                    return

                # Local import — mirrors the existing lazy-import convention
                # for cross-package deps in this codebase (see
                # api/dependencies.get_leaderboard_points_service) and keeps
                # leaderboard_points from depending on quiz.repositories at
                # module-import time.
                from quiz.repositories.leaderboard_hidden import (
                    LeaderboardHiddenRepository,
                )

                hidden_ids = LeaderboardHiddenRepository(self.repo.db).get_all()
                if str(user_id) in hidden_ids:
                    return

                week_start_at, week_end_at = current_week_bounds_almaty(datetime.now(UTC))
                # The caller added its PointsAuditLog row to the session but
                # has not committed; flush so the aggregate below counts the
                # award that triggered this hook.
                self.repo.db.flush()
                rows = self.repo.weekly_points(week_start_at, week_end_at, [user_id])
                week_points = rows[0][1] if rows else 0
                if week_points < target:
                    return

                self.repo.try_lock_sprint_winner(week_start_at, user_id, week_points)
        except Exception:
            logger.exception(
                "check_and_lock_sprint_winner failed for user %s (non-fatal, "
                "points award itself is unaffected)",
                user_id,
            )

    def get_sprint_status_raw(
        self,
    ) -> tuple[int | None, datetime | None, tuple[UUID, int, datetime] | None]:
        """Returns `(target_points, week_start_at, winner_row)` for
        `GET /leaderboard/sprint`. `winner_row` is the raw `(user_id,
        points_at_win, won_at)` tuple — display-name/avatar resolution
        happens at the route layer, reusing the same Keycloak/cache/
        user_display lookup `GET /leaderboard` already uses, rather than
        a second mechanism here. `week_start_at` is None iff
        `target_points` is None/0 (feature off)."""
        settings = self.repo.get_or_create_settings()
        target = settings.sprint_target_points
        if not target:
            return None, None, None
        week_start_at = current_week_start_almaty(datetime.now(UTC))
        winner_row = self.repo.get_current_sprint_winner_row(week_start_at)
        return target, week_start_at, winner_row
