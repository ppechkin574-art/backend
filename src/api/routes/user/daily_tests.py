from fastapi import APIRouter, Body, Depends, HTTPException, Query
from starlette import status

from api.dependencies import (
    get_daily_test_service,
    get_student,
    get_user,
    require_active_subscription,
)
from api.middlewares.locale import get_locale
from api.exceptions.documentation import get_common_responses, get_daily_test_responses
from quiz.dtos.daily_tests import (
    DailyTestAnswerRequestDTO,
    DailyTestAttemptDetailDTO,
    DailyTestAttemptDTO,
    DailyTestDeviceTokenDTO,
    DailyTestHistoryItemDTO,
    DailyTestResultDTO,
    DailyTestTodayRequestDTO,
    RegisterDailyTestDeviceTokenDTO,
    SubjectPreferencesResponseDTO,
    UpdateSubjectPreferencesDTO,
)
from quiz.services.daily_tests import DailyTestService
from student import StudentDTO
from utils.monitoring import log_info, log_warning

router = APIRouter(
    prefix="/user/daily-tests",
    tags=["User - Daily Tests"],
    dependencies=[Depends(get_user)],
)


@router.get(
    "/subjects",
    response_model=SubjectPreferencesResponseDTO,
    summary="Получить выбранные предметы",
    description="Возвращает список выбранных предметов для ежедневных тестов",
    responses={**get_common_responses("read")},
)
async def get_subject_preferences(
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
):
    log_info(
        "Get daily test subject preferences request",
        user_id=student.id,
        action="get_daily_test_subject_preferences",
        resource="daily_test_subjects",
    )

    result = service.get_subject_preferences(student.id)

    log_info(
        "Daily test subject preferences retrieved successfully",
        user_id=student.id,
        action="get_daily_test_subject_preferences",
        resource="daily_test_subjects",
        count=len(result.subjects),
    )
    return result


@router.patch(
    "/subjects",
    response_model=SubjectPreferencesResponseDTO,
    summary="Обновить выбранные предметы",
    description="Обновляет список предметов для ежедневных тестов (минимум 2, максимум 5)",
    responses={**get_common_responses("update")},
)
async def update_subject_preferences(
    data: UpdateSubjectPreferencesDTO,
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Update daily test subject preferences request",
        user_id=student.id,
        action="update_daily_test_subject_preferences",
        resource="daily_test_subjects",
        subject_ids=data.subject_ids,
    )

    try:
        result = service.update_subject_preferences(student.id, data)
    except ValueError as e:
        log_warning(
            "Failed to update daily test subject preferences",
            user_id=student.id,
            action="update_daily_test_subject_preferences",
            resource="daily_test_subjects",
            error=str(e),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log_info(
        "Daily test subject preferences updated successfully",
        user_id=student.id,
        action="update_daily_test_subject_preferences",
        resource="daily_test_subjects",
        count=len(result.subjects),
    )
    return result


@router.post(
    "/devices/token",
    response_model=DailyTestDeviceTokenDTO,
    summary="Сохранить FCM токен устройства",
    description="Сохраняет токен устройства для уведомлений о ежедневных тестах",
    responses={**get_common_responses("create")},
)
async def register_device_token(
    data: RegisterDailyTestDeviceTokenDTO,
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
):
    log_info(
        "Register daily test device token request",
        user_id=student.id,
        action="register_daily_test_device_token",
        resource="daily_test_device_tokens",
        platform=data.platform,
    )

    try:
        result = service.register_device_token(student.id, data)
    except ValueError as exc:
        log_warning(
            "Failed to register daily test device token",
            user_id=student.id,
            action="register_daily_test_device_token",
            resource="daily_test_device_tokens",
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    log_info(
        "Daily test device token registered successfully",
        user_id=student.id,
        action="register_daily_test_device_token",
        resource="daily_test_device_tokens",
        token_suffix=result.token[-6:] if len(result.token) > 6 else result.token,
    )
    return result


@router.get(
    "/today",
    response_model=DailyTestAttemptDTO,
    summary="Получить тест на сегодня",
    description="Возвращает ежедневный тест на сегодня. Можно указать конкретный предмет по ID, чтобы получить 5 вопросов по нему.",
    responses={**get_common_responses("read")},
)
async def get_today_test(
    subject_id: int | None = Query(
        None,
        description="ID предмета, по которому нужно получить тест (опционально)",
    ),
    payload: DailyTestTodayRequestDTO | None = Body(None, description="Опциональный JSON с ID предмета"),
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    locale: str = Depends(get_locale),
    _=Depends(require_active_subscription()),
):
    resolved_subject_id = subject_id or (payload.subject_id if payload else None)

    log_info(
        "Get today's daily test request",
        user_id=student.id,
        action="get_today_daily_test",
        resource="daily_test",
        subject_id=resolved_subject_id,
        locale=locale,
    )

    try:
        result = service.get_today_test(student.id, resolved_subject_id, locale=locale)
    except ValueError as e:
        log_warning(
            "Failed to get today's daily test",
            user_id=student.id,
            action="get_today_daily_test",
            resource="daily_test",
            error=str(e),
            subject_id=resolved_subject_id,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log_info(
        "Today's daily test retrieved successfully",
        user_id=student.id,
        action="get_today_daily_test",
        resource="daily_test",
        attempt_id=result.id,
        question_count=result.total_questions,
        subject_id=resolved_subject_id or result.subject_id,
    )
    return result


@router.post(
    "/attempts/answer",
    response_model=DailyTestResultDTO,
    summary="Отправить ответы на ежедневный тест",
    description="Отправляет ответы на вопросы ежедневного теста и возвращает результат",
    responses=get_daily_test_responses("create"),
)
async def submit_daily_test_answers(
    data: DailyTestAnswerRequestDTO,
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Submit daily test answers request",
        user_id=student.id,
        action="submit_daily_test_answers",
        resource="daily_test_attempt",
        attempt_id=data.attempt_id,
        answer_count=len(data.questions),
    )

    result = service.submit_answers(student.id, data)

    log_info(
        "Daily test answers submitted successfully",
        user_id=student.id,
        action="submit_daily_test_answers",
        resource="daily_test_attempt",
        attempt_id=data.attempt_id,
        score=result.score,
        correct=result.correct_answers,
    )
    return result


@router.get(
    "/attempts",
    response_model=list[DailyTestHistoryItemDTO],
    summary="История ежедневных тестов",
    description="Возвращает историю всех пройденных ежедневных тестов",
    responses={**get_common_responses("read")},
)
async def get_daily_tests_history(
    limit: int | None = Query(None, ge=1, le=100, description="Лимит записей"),
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Get daily tests history request",
        user_id=student.id,
        action="get_daily_tests_history",
        resource="daily_test_attempts",
        limit=limit,
    )

    result = service.get_attempts_history(student.id, limit)

    log_info(
        "Daily tests history retrieved successfully",
        user_id=student.id,
        action="get_daily_tests_history",
        resource="daily_test_attempts",
        count=len(result),
    )
    return result


@router.get(
    "/today/results",
    response_model=list[DailyTestHistoryItemDTO],
    summary="Результаты сегодняшних тестов",
    description="Возвращает все ежедневные тесты за текущий день по времени Астаны (GMT+5)",
    responses={**get_common_responses("read")},
)
async def get_today_daily_tests_results(
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Get today's daily test results request",
        user_id=student.id,
        action="get_today_daily_tests_results",
        resource="daily_test_attempts",
    )

    result = service.get_today_attempts(student.id)

    log_info(
        "Today's daily test results retrieved successfully",
        user_id=student.id,
        action="get_today_daily_tests_results",
        resource="daily_test_attempts",
        count=len(result),
    )
    return result


@router.get(
    "/attempts/{attempt_id}",
    response_model=DailyTestAttemptDetailDTO,
    summary="Детали попытки ежедневного теста",
    description="Возвращает детальную информацию о попытке с ответами пользователя и правильными ответами",
    responses=get_daily_test_responses("read"),
)
async def get_daily_test_attempt_detail(
    attempt_id: int,
    student: StudentDTO = Depends(get_student),
    service: DailyTestService = Depends(get_daily_test_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Get daily test attempt detail request",
        user_id=student.id,
        action="get_daily_test_attempt_detail",
        resource="daily_test_attempt",
        attempt_id=attempt_id,
    )

    result = service.get_attempt_detail(attempt_id, student.id)

    log_info(
        "Daily test attempt detail retrieved successfully",
        user_id=student.id,
        action="get_daily_test_attempt_detail",
        resource="daily_test_attempt",
        attempt_id=attempt_id,
    )
    return result
