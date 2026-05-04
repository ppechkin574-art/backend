from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from api.dependencies import (
    get_family_service,
    get_statistic_service,
    get_student,
    get_user,
    require_active_subscription,
)
from api.exceptions.documentation import get_common_responses, get_error_responses
from auth.dtos.users import UserDTO
from quiz.services.family import FamilyService
from quiz.dtos.enums import ExamType
from quiz.dtos.statistic import (
    EnhancedGlobalStatisticDTO,
    EntStatisticGetServiceDTO,
    EntStatisticServiceDTO,
    StatisticPeriodType,
    StatisticRequestDTO,
    TopicStatisticGetServiceDTO,
    TopicStatisticServiceDTO,
)
from quiz.exceptions import StatisticDoesNotExist
from quiz.services.statistic import StatisticService
from student import StudentDTO
from utils.monitoring import log_info, log_warning

router = APIRouter(
    prefix="/user/statistics",
    tags=["User - Education statistics"],
    dependencies=[Depends(get_user), Depends(require_active_subscription())],
)


@router.get(
    "/ents",
    response_model=EntStatisticServiceDTO,
    summary="Статистика по ЕНТ",
    description="Возвращает статистику пользователя по ЕНТ за период",
    responses={
        **get_common_responses("read"),
        **get_error_responses(StatisticDoesNotExist),
    },
    deprecated=True,
)
async def get_ent_statistics(
    date_start: date = Query(..., description="Начальная дата периода"),
    date_end: date = Query(..., description="Конечная дата периода"),
    exam_type: ExamType = Query(ExamType.by_subject, description="Тип экзамена"),
    student: StudentDTO = Depends(get_student),
    service: StatisticService = Depends(get_statistic_service),
):
    if date_start > date_end:
        log_warning(
            "Invalid date range for ENT statistics",
            user_id=student.id,
            action="get_ent_statistics",
            resource="ent_statistics",
            error_type="InvalidDateRange",
            date_start=date_start.isoformat(),
            date_end=date_end.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    log_info(
        "ENT statistics request",
        user_id=student.id,
        action="get_ent_statistics",
        resource="ent_statistics",
        exam_type=exam_type.value,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
    )

    stat_params = EntStatisticGetServiceDTO(
        student_guid=student.id,
        ts_start=int(datetime.combine(date_start, time.min).timestamp()),
        ts_end=int(datetime.combine(date_end, time.max).timestamp()),
        exam_type=exam_type,
    )
    result = await service.get_ent_statistic(stat_params)

    log_info(
        "ENT statistics retrieved successfully",
        user_id=student.id,
        action="get_ent_statistics",
        resource="ent_statistics",
        exam_type=exam_type.value,
    )
    return result


@router.get(
    "/ents/subject/{subject_id}",
    response_model=EntStatisticServiceDTO,
    summary="Статистика ЕНТ по предмету",
    description="Возвращает статистику ЕНТ для конкретного предмета за период",
    responses={
        **get_common_responses("read"),
        **get_error_responses(StatisticDoesNotExist),
    },
    deprecated=True,
)
async def get_ent_statistics_by_subject(
    subject_id: int,
    date_start: date = Query(..., description="Начальная дата периода"),
    date_end: date = Query(..., description="Конечная дата периода"),
    exam_type: ExamType = Query(ExamType.by_subject, description="Тип экзамена"),
    student: StudentDTO = Depends(get_student),
    service: StatisticService = Depends(get_statistic_service),
):
    """Статистика ЕНТ по предмету"""
    if date_start > date_end:
        log_warning(
            "Invalid date range for ENT subject statistics",
            user_id=student.id,
            action="get_ent_statistics_by_subject",
            resource="ent_statistics",
            error_type="InvalidDateRange",
            subject_id=subject_id,
            exam_type=exam_type.value,
            date_start=date_start.isoformat(),
            date_end=date_end.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    log_info(
        "ENT subject statistics request",
        user_id=student.id,
        action="get_ent_statistics_by_subject",
        resource="ent_statistics",
        subject_id=subject_id,
        exam_type=exam_type.value,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
    )

    result = await service.get_ent_statistic_by_subject(
        student.id,
        subject_id,
        int(datetime.combine(date_start, time.min).timestamp()),
        int(datetime.combine(date_end, time.max).timestamp()),
        exam_type,
    )

    log_info(
        "ENT subject statistics retrieved successfully",
        user_id=student.id,
        action="get_ent_statistics_by_subject",
        resource="ent_statistics",
        subject_id=subject_id,
        exam_type=exam_type.value,
    )
    return result


@router.get(
    "/topics/{topic_id}",
    response_model=TopicStatisticServiceDTO,
    summary="Статистика по теме",
    description="Возвращает статистику пользователя по теме за период",
    responses={
        **get_common_responses("read"),
        **get_error_responses(StatisticDoesNotExist),
    },
    deprecated=True,
)
async def get_topic_statistics(
    topic_id: int,
    date_start: date = Query(..., description="Начальная дата периода"),
    date_end: date = Query(..., description="Конечная дата периода"),
    student: StudentDTO = Depends(get_student),
    service: StatisticService = Depends(get_statistic_service),
):
    if date_start > date_end:
        log_warning(
            "Invalid date range for topic statistics",
            user_id=student.id,
            action="get_topic_statistics",
            resource="topic_statistics",
            error_type="InvalidDateRange",
            topic_id=topic_id,
            date_start=date_start.isoformat(),
            date_end=date_end.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    log_info(
        "Topic statistics request",
        user_id=student.id,
        action="get_topic_statistics",
        resource="topic_statistics",
        topic_id=topic_id,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
    )

    stat_params = TopicStatisticGetServiceDTO(
        student_guid=student.id,
        topic_id=topic_id,
        ts_start=int(datetime.combine(date_start, time.min).timestamp()),
        ts_end=int(datetime.combine(date_end, time.max).timestamp()),
    )
    result = await service.get_trainer_topic_statistic(stat_params)

    log_info(
        "Topic statistics retrieved successfully",
        user_id=student.id,
        action="get_topic_statistics",
        resource="topic_statistics",
        topic_id=topic_id,
    )
    return result


@router.get(
    "/topics/subject/{subject_id}",
    summary="Статистика тренажеров по предмету",
    description="Возвращает статистику тренажеров по всем темам предмета за период",
    responses=get_common_responses("read"),
    deprecated=True,
)
async def get_topic_statistics_by_subject(
    subject_id: int,
    date_start: date = Query(..., description="Начальная дата периода"),
    date_end: date = Query(..., description="Конечная дата периода"),
    student: StudentDTO = Depends(get_student),
    service: StatisticService = Depends(get_statistic_service),
):
    """Статистика тренажеров по предмету"""
    if date_start > date_end:
        log_warning(
            "Invalid date range for topic subject statistics",
            user_id=student.id,
            action="get_topic_statistics_by_subject",
            resource="topic_statistics",
            error_type="InvalidDateRange",
            subject_id=subject_id,
            date_start=date_start.isoformat(),
            date_end=date_end.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    log_info(
        "Topic subject statistics request",
        user_id=student.id,
        action="get_topic_statistics_by_subject",
        resource="topic_statistics",
        subject_id=subject_id,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
    )

    result = service.get_trainer_topic_statistic_by_subject(
        student.id,
        subject_id,
        int(datetime.combine(date_start, time.min).timestamp()),
        int(datetime.combine(date_end, time.max).timestamp()),
    )

    log_info(
        "Topic subject statistics retrieved successfully",
        user_id=student.id,
        action="get_topic_statistics_by_subject",
        resource="topic_statistics",
        subject_id=subject_id,
    )
    return result


@router.get(
    "/global",
    response_model=EnhancedGlobalStatisticDTO,
    summary="Расширенная глобальная статистика",
    description="""
    Получить расширенную статистику по всем категориям с поддержкой разных периодов:

    Типы периодов:
    - last_7_days: Последние 7 дней (включая сегодня)
    - last_30_days: Последние 30 дней (включая сегодня)
    - calendar_week: Календарная неделя (пн-вс), требует параметр week_date
    - calendar_month: Календарный месяц, требует параметр month_year
    - custom: Произвольный период, требует параметры custom_start_date и custom_end_date

    В статистику входят:
    - ЕНТ варианты: количество попыток, точность, прогресс по предметам
    - Тренажеры: количество решенных, точность, прогресс по темам и предметам
    - Ежедневные задания: количество, текущий страйк, прогресс по предметам

    Дополнительно:
    - История страйков за период
    - Уровень активности (low, medium, high, very_high)
    - Балл вовлеченности (0-100)
    - Персональные рекомендации
    """,
    responses=get_common_responses("read"),
)
def get_enhanced_global_statistic(
    period_type: StatisticPeriodType = Query(StatisticPeriodType.LAST_7_DAYS),
    week_date: date = Query(None),
    month_year: str = Query(None),
    custom_start_date: date = Query(None),
    custom_end_date: date = Query(None),
    subject_id: int = Query(None),
    exam_type: ExamType = Query(ExamType.by_subject),
    user_id: UUID | None = Query(None, description="ID ребёнка (только для родителей)"),
    user: UserDTO = Depends(get_user),
    service: StatisticService = Depends(get_statistic_service),
    family_service: FamilyService = Depends(get_family_service),
):
    student_id = user.id

    if user_id is not None:
        if "parent" not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only parents can request statistics for another user",
            )
        children = family_service.get_children(user)
        if not any(child["user_id"] == user_id for child in children):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not connected to this child",
            )
        student_id = user_id

    request = StatisticRequestDTO(
        period_type=period_type,
        week_date=week_date,
        month_year=month_year,
        custom_start_date=custom_start_date,
        custom_end_date=custom_end_date,
        subject_id=subject_id,
        exam_type=exam_type,
        user_id=user_id,
    )

    if period_type == StatisticPeriodType.CALENDAR_WEEK and not week_date:
        raise HTTPException(400, "week_date required")
    if period_type == StatisticPeriodType.CALENDAR_MONTH and not month_year:
        raise HTTPException(400, "month_year required")
    if period_type == StatisticPeriodType.CUSTOM and (
        not custom_start_date or not custom_end_date
    ):
        raise HTTPException(400, "custom_start_date and custom_end_date required")

    return service.get_enhanced_global_statistic(student_id, request)
