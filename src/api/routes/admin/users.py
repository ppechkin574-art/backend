from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import (
    allow_only_admins,
    get_admin_user_service,
    get_cache_service,
    get_unit_of_work_tests,
)
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
    dependencies=[Depends(allow_only_admins)],
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

    Admin-only (this whole router is `allow_only_admins`).
    """
    return service.reset_subscription(user_id)


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
