"""User-facing daily-streak coin bonus.

GET  /user/daily-streak/status  — snapshot for the modal trigger
POST /user/daily-streak/claim   — credit today's bonus, return balance

Streak count is fetched from the attendance pipeline so we never
double-source it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from sqlalchemy import select

from api.dependencies import (
    get_db_session,
    get_streak_bonus_service,
    get_user,
)
from auth.dtos.users import UserDTO
from quiz.models.attendance_streak import AttendanceStreak
from streak_bonus.dtos import ClaimResultDTO, DailyStreakStatusDTO
from streak_bonus.service import StreakBonusService

router = APIRouter(
    prefix="/user/daily-streak",
    tags=["User - Daily Streak"],
    dependencies=[Depends(get_user)],
)


def _current_streak(user_id, db: Session) -> int:
    """Read `attendance_streaks.current_streak_days` for the user.
    Falls back to 0 on error so a flaky attendance read doesn't break
    the modal / balance endpoint."""
    try:
        row = db.scalars(
            select(AttendanceStreak).where(
                AttendanceStreak.student_guid == user_id
            )
        ).first()
        return int(row.current_streak_days) if row and row.current_streak_days else 0
    except Exception:
        return 0


@router.get("/status", response_model=DailyStreakStatusDTO)
def get_status(
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    return service.get_status(user.id, _current_streak(user.id, db))


@router.post("/claim", response_model=ClaimResultDTO)
def claim(
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    result = service.claim(user.id, _current_streak(user.id, db))
    service.repo.db.commit()
    return result
