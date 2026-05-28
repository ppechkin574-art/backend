"""User-facing daily-streak coin bonus.

GET  /user/daily-streak/status  — snapshot for the modal trigger
POST /user/daily-streak/claim   — credit today's bonus, return balance

Streak count is fetched from the same AttendanceService source the
Statistics screen and Profile pills use, so the bonus modal stays
aligned with what the rest of the app shows.
"""

from fastapi import APIRouter, Depends

from api.dependencies import (
    get_attendance_service,
    get_streak_bonus_service,
    get_user,
)
from auth.dtos.users import UserDTO
from quiz.services.attendance import AttendanceService
from streak_bonus.dtos import ClaimResultDTO, DailyStreakStatusDTO
from streak_bonus.service import StreakBonusService

router = APIRouter(
    prefix="/user/daily-streak",
    tags=["User - Daily Streak"],
    dependencies=[Depends(get_user)],
)


def _current_streak(user_id, attendance: AttendanceService) -> int:
    """Routed through AttendanceService.get_attendance_info so seed-
    streak admin endpoint (which backfills DailyTestAttempts) shows
    up immediately — reading raw `attendance_streaks.current_streak_days`
    would miss those because the seed doesn't touch the streak table.
    """
    try:
        info = attendance.get_attendance_info(user_id)
        return int(info.streak.current_days or 0)
    except Exception:
        return 0


@router.get("/status", response_model=DailyStreakStatusDTO)
def get_status(
    user: UserDTO = Depends(get_user),
    attendance: AttendanceService = Depends(get_attendance_service),
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    return service.get_status(user.id, _current_streak(user.id, attendance))


@router.post("/claim", response_model=ClaimResultDTO)
def claim(
    user: UserDTO = Depends(get_user),
    attendance: AttendanceService = Depends(get_attendance_service),
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    result = service.claim(user.id, _current_streak(user.id, attendance))
    service.repo.db.commit()
    return result
