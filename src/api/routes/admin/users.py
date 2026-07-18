from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.dependencies import (
    allow_read_or_admin_write,
    get_admin_user_service,
    get_cache_service,
    get_database,
    get_unit_of_work_tests,
)
from database import Database
from auth.admin_service import AdminUserService
from auth.dtos.admin import (
    AdminUserCreateDTO,
    AdminUserCreateResponseDTO,
    AdminUserUpdateDTO,
)
from auth.dtos.users import UserDTO
from quiz.uows.uows import UnitOfWorkTests
from quiz.utils.period.init import KZ_TZ, today_kz
from utils.cache import CacheService

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin - Users"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get("", response_model=list[UserDTO])
async def get_users(
    role: str | None = None,
    search: str | None = None,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.get_users(role=role, search=search)


@router.post("", response_model=AdminUserCreateResponseDTO, status_code=201)
async def create_user(
    data: AdminUserCreateDTO,
    service: AdminUserService = Depends(get_admin_user_service),
):
    try:
        return service.create_user(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{user_id}", response_model=UserDTO)
async def get_user(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserDTO)
async def update_user(
    user_id: UUID,
    data: AdminUserUpdateDTO,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.update_user(user_id, data)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    service.delete_user(user_id)
    return None


@router.post("/{user_id}/reset-subscription", response_model=UserDTO)
async def reset_subscription(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Forcibly rewind the user's subscription to FREE.

    Used to prepare demo accounts (e.g. Apple Reviewer) before
    submitting a build for App Store review — the reviewer needs
    to see "Купить подписку" rather than the cancel CTA, so any
    pre-existing PRO state has to be wiped from Keycloak attrs.
    The regular `cancel_subscription` endpoint is a soft-cancel
    and won't help here (it leaves plan=PRO until subscription_end).

    Admin-only (this whole router is `allow_read_or_admin_write`).
    """
    return service.reset_subscription(user_id)


class GrantProSubscriptionRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=3650)


@router.post("/{user_id}/grant-pro-subscription", response_model=UserDTO)
async def grant_pro_subscription(
    user_id: UUID,
    payload: GrantProSubscriptionRequest,
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Forcibly grant a PRO subscription for `days` days (default 30).

    Companion to `/reset-subscription` (which sets plan=FREE). Used when:
      - A paying user's IAP receipt failed to propagate to the backend
        (real money was charged but plan stayed FREE). One-shot grant
        unblocks them while the receipt-validation bug is fixed.
      - Apple/Google reviewers need PRO access to exercise the gated
        flows (test creation, etc.) before approving a build.
      - Customer support needs to comp a user.

    Admin-only (this whole router is `allow_read_or_admin_write`).
    """
    try:
        return service.grant_pro_subscription(user_id, days=payload.days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class SeedStreakRequest(BaseModel):
    days: int = Field(default=3, ge=1, le=30)


class SeedStreakResponse(BaseModel):
    user_id: UUID
    days_added: int
    seeded_dates_kz: list[str]


@router.post("/{user_id}/seed-streak", response_model=SeedStreakResponse)
async def seed_streak(
    user_id: UUID,
    payload: SeedStreakRequest,
    uow: UnitOfWorkTests = Depends(get_unit_of_work_tests),
    cache_service: CacheService = Depends(get_cache_service),
):
    """Insert N consecutive «completed daily test» rows for `user_id`
    ending today (Almaty calendar) — fastest way to give a QA / demo
    account a visible streak on the Statistics screen without going
    through the actual training flow N times.

    Each fake attempt is a real DailyTestAttempt with status=completed
    and completed_at=12:00 Almaty of that day → StatisticService
    will pick them up via _get_completed_dates_for_daily and the
    «Стрик тренировок» card will show N.

    Cache is invalidated for the user's `enhanced_global_statistic`
    resource so the change shows up on the very next GET /stats call,
    no manual wait for the 1h TTL.

    Admin-only. Calling it twice creates duplicate rows — they don't
    affect the streak value (set semantics in the calculator collapses
    them by date) but do inflate row counts. Acceptable for the QA /
    demo use case this exists for.
    """
    from datetime import UTC, datetime, time, timedelta

    from quiz.dtos.daily_tests import DailyTestAttemptCreateRepositoryDTO

    today = today_kz()
    seeded_dates: list[str] = []
    try:
        with uow:
            for offset in range(payload.days):
                kz_date = today - timedelta(days=offset)
                # 12:00 Almaty time of that day → naive UTC equivalent
                # for storage in the completed_at column (matches the
                # naive-UTC DB convention).
                completed_at_utc = (
                    datetime.combine(kz_date, time(hour=12), tzinfo=KZ_TZ)
                    .astimezone(UTC)
                    .replace(tzinfo=None)
                )
                attempt = uow.daily_tests.create_attempt(
                    DailyTestAttemptCreateRepositoryDTO(
                        student_guid=user_id,
                        test_date=kz_date,
                        status="completed",
                        subject_id=None,
                    )
                )
                # create_attempt only sets started_at via server_default.
                # Set completed_at explicitly so it's picked up by the
                # streak query (which filters on attempt.completed_at).
                attempt.completed_at = completed_at_utc
                seeded_dates.append(kz_date.isoformat())
            # UoW context manager commits on successful exit, no need to
            # call uow.commit() explicitly.
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to seed streak: {e}",
        ) from e

    # Bust the user's cached statistics so the new rows are visible
    # immediately on the next /stats call (TTL is 1h otherwise).
    cache_service.invalidate_by_resource(
        "enhanced_global_statistic", user_id=user_id
    )

    return SeedStreakResponse(
        user_id=user_id,
        days_added=len(seeded_dates),
        seeded_dates_kz=seeded_dates,
    )


# ---------------------------------------------------------------------------
# Activity stats: active hours + avg session length per user
# ---------------------------------------------------------------------------

class ActivityHourSlot(BaseModel):
    hour: int      # 0-23 (Almaty time)
    count: int     # number of app-opens in this hour


class UserActivityStatsDTO(BaseModel):
    active_hours: list[ActivityHourSlot]   # 24 slots, some may be 0
    avg_session_minutes: float | None      # None if < 2 opens total
    total_opens_30d: int
    last_platform: str | None             # most recent recorded platform


@router.get("/{user_id}/activity", response_model=UserActivityStatsDTO)
async def get_user_activity(
    user_id: UUID,
    database: Database = Depends(get_database),
):
    """Return per-user activity statistics derived from app-open events.

    active_hours — count of app-opens per hour of day (Almaty TZ) over last 30 days.
    avg_session_minutes — Approach B: consecutive events within 30 min = one session.
    """
    since = datetime.now(UTC) - timedelta(days=30)

    session = database.session
    try:
        rows = session.execute(
            text(
                "SELECT occurred_at, platform FROM user_activity_events "
                "WHERE user_id = :uid AND occurred_at >= :since "
                "ORDER BY occurred_at ASC"
            ),
            {"uid": str(user_id), "since": since},
        ).fetchall()
    finally:
        session.close()

    if not rows:
        return UserActivityStatsDTO(
            active_hours=[ActivityHourSlot(hour=h, count=0) for h in range(24)],
            avg_session_minutes=None,
            total_opens_30d=0,
            last_platform=None,
        )

    from zoneinfo import ZoneInfo
    almaty = ZoneInfo("Asia/Almaty")

    # Active hours histogram
    hour_counts: dict[int, int] = {h: 0 for h in range(24)}
    for row in rows:
        local_hour = row[0].astimezone(almaty).hour
        hour_counts[local_hour] += 1

    # Average session length — approach B: gap < 30 min → same session
    SESSION_GAP = timedelta(minutes=30)
    timestamps = [r[0] for r in rows]
    sessions: list[timedelta] = []
    sess_start = timestamps[0]
    sess_last = timestamps[0]
    for ts in timestamps[1:]:
        if ts - sess_last < SESSION_GAP:
            sess_last = ts
        else:
            sessions.append(sess_last - sess_start)
            sess_start = ts
            sess_last = ts
    sessions.append(sess_last - sess_start)

    avg_minutes: float | None = None
    if sessions:
        total_secs = sum(s.total_seconds() for s in sessions)
        avg_minutes = round(total_secs / len(sessions) / 60, 1)

    last_platform = rows[-1][1] if rows else None

    return UserActivityStatsDTO(
        active_hours=[ActivityHourSlot(hour=h, count=hour_counts[h]) for h in range(24)],
        avg_session_minutes=avg_minutes,
        total_opens_30d=len(rows),
        last_platform=last_platform,
    )
