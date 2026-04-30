from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import (
    get_attendance_service,
    get_student,
    get_user,
    require_active_subscription,
)
from quiz.dtos.attendance import (
    AttendanceFullDTO,
)
from quiz.services.attendance import AttendanceService
from student.dtos.student import StudentDTO
from utils.monitoring import log_info

router = APIRouter(
    prefix="/user/attendance",
    tags=["User - Attendance"],
    dependencies=[Depends(get_user), Depends(require_active_subscription())],
)


@router.get(
    "/",
    response_model=AttendanceFullDTO,
    summary="Полная информация о посещениях",
)
async def get_attendance_info(
    year: int | None = Query(None, ge=2024, le=2026, description="Год (по умолчанию текущий)"),
    month: int | None = Query(None, ge=1, le=12, description="Месяц 1-12 (по умолчанию текущий)"),
    student: StudentDTO = Depends(get_student),
    attendance_service: AttendanceService = Depends(get_attendance_service),
):
    """
    Получить полную информацию о посещаемости:
    - Текущий стрик (дни подряд, общие баллы)
    - Информация о цикле (текущий день в цикле, номер цикла, множитель)
    - Календарь за указанный месяц с датами посещений

    Если год и месяц не указаны - возвращает за текущий месяц.
    """
    current_date = datetime.now(UTC).date()

    if year is not None and month is not None:
        requested_date = date(year, month, 1)
        if requested_date > current_date.replace(day=1):
            raise HTTPException(
                status_code=400,
                detail=f"Невозможно запросить данные за будущий месяц. Текущий месяц: {current_date.year}-{current_date.month}",
            )

    log_info(
        "Attendance info request",
        user_id=student.id,
        year=year,
        month=month,
        action="get_attendance_info",
        resource="attendance",
    )

    result = attendance_service.get_attendance_info(student.id, year, month)
    return result


@router.post(
    "/record",
    response_model=AttendanceFullDTO,
    summary="Зафиксировать посещение вручную",
    description="""
    Ручная фиксация посещения (в основном для тестирования).
    В продакшене используется автоматическая запись через активность.
    """,
    include_in_schema=False,
)
async def record_attendance_manual(
    student=Depends(get_student),
    attendance_service: AttendanceService = Depends(get_attendance_service),
):
    """Ручная запись посещения (для тестирования)"""
    log_info(
        "Manual attendance record",
        user_id=student.id,
        action="record_attendance_manual",
        resource="attendance",
    )

    result = attendance_service.record_attendance(student.id)

    log_info(
        "Attendance manually recorded",
        user_id=student.id,
        streak_days=result.streak.current_days,
        points_awarded=result.streak.today_points,
        total_points=result.streak.total_points,
    )

    return result
