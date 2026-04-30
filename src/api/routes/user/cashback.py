from datetime import date

from fastapi import APIRouter, Depends, Query

from api.dependencies import (
    get_cashback_service,
    get_student,
    get_user,
)
from quiz.dtos.cashback import (
    CashbackActivityFeedResponseDTO,
    CashbackDailyStatsResponseDTO,
    CashbackHistoryDTO,
    CashbackStatusDTO,
    CashbackTodayDTO,
)
from quiz.services.cashback import CashbackService
from student.dtos.student import StudentDTO

router = APIRouter(
    prefix="/user/cashback",
    tags=["User - Cashback"],
    dependencies=[Depends(get_user)],
)


@router.get("/status", response_model=CashbackStatusDTO)
async def get_cashback_status(
    student: StudentDTO = Depends(get_student),
    cashback_service: CashbackService = Depends(get_cashback_service),
):
    """Текущий прогресс в системе кешбека."""
    return cashback_service.get_status(student.id)


@router.get("/today", response_model=CashbackTodayDTO)
async def get_cashback_today(
    student: StudentDTO = Depends(get_student),
    cashback_service: CashbackService = Depends(get_cashback_service),
):
    """Статус выполнения условий на сегодня."""
    return cashback_service.get_today_status(student.id)


@router.get("/daily-stats", response_model=CashbackDailyStatsResponseDTO)
async def get_cashback_daily_stats(
    start_date: date | None = Query(None, description="Начальная дата (по Астане)"),
    end_date: date | None = Query(None, description="Конечная дата (по Астане)"),
    student: StudentDTO = Depends(get_student),
    cashback_service: CashbackService = Depends(get_cashback_service),
):
    """Детальная статистика по дням за период."""
    return cashback_service.get_daily_stats(student.id, start_date, end_date)


@router.get("/activity-feed", response_model=CashbackActivityFeedResponseDTO)
async def get_cashback_activity_feed(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    student: StudentDTO = Depends(get_student),
    cashback_service: CashbackService = Depends(get_cashback_service),
):
    """Лента активности пользователя (все действия, влияющие на кешбек)."""
    return cashback_service.get_activity_feed(student.id, limit, offset)


@router.get("/history", response_model=CashbackHistoryDTO)
async def get_cashback_history(
    limit: int = Query(100, ge=1, le=500),
    student: StudentDTO = Depends(get_student),
    cashback_service: CashbackService = Depends(get_cashback_service),
):
    """История начислений кешбека."""
    return cashback_service.get_history(student.id, limit)
