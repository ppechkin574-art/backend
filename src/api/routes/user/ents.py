from datetime import UTC

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from api.dependencies import (
    get_ent_attempts_service,
    get_ent_options_service,
    get_student,
    get_subject_combination_service,
    get_user,
    require_active_subscription,
)
from api.middlewares.locale import get_locale
from api.exceptions.documentation import (
    get_common_responses,
    get_ent_responses,
    get_error_responses,
)
from api.routes.quiz.converters import (
    to_ent_attempt_answer,
    to_ent_attempt_create_dto_service,
    to_ent_options_get_service,
)
from api.routes.quiz.dtos import (
    EntAttemptAnswerRequestDTO,
    StartAttemptRequestDTO,
    StartFullExamRequestDTO,
    SubjectCombinationResponseDTO,
)
from quiz.dtos.ent_attempts import (
    EntAttemptDetailWithAnswersDTO,
    EntAttemptHistoryItemDTO,
    EntAttemptServiceDTO,
    EntAttemptStatisticServiceDTO,
    UpdateQuestionIndexResponseDTO,
)
from quiz.dtos.ent_options import EntOptionsServiceDTO, EntOptionsServiceResponceDTO
from quiz.exceptions import (
    AlreadyAnswered,
    EntOptionsDoesntExist,
    QuestionNotFound,
    TrainerAttemptNotExist,
    VariantNotExist,
    WrongStudent,
)
from quiz.services.ent_attempts import EntAttemptServiceInterface
from quiz.services.ent_options import EntOptionServiceInterface
from quiz.services.subject_combinations import SubjectCombinationService
from student import StudentDTO
from utils.monitoring import log_info

router = APIRouter(prefix="/user/ents", tags=["User - ENTs"], dependencies=[Depends(get_user)])


@router.get(
    "",
    response_model=EntOptionsServiceResponceDTO,
    summary="Получить ЕНТ варианты",
    description="Возвращает все доступные ЕНТ варианты",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_ent_options(
    subject_id: int | None = Query(None, description="Фильтр по предмету"),
    student: StudentDTO = Depends(get_student),
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    log_info(
        "ENT options request",
        user_id=student.id,
        action="get_ent_options",
        resource="ent_options",
        subject_id=subject_id,
    )
    result = service.get_ents(to_ent_options_get_service(subject_id, student))
    log_info(
        "ENT options retrieved successfully",
        user_id=student.id,
        action="get_ent_options",
        resource="ent_options",
        count=len(result) if result else 0,
    )
    return EntOptionsServiceResponceDTO(count=len(result) if result else 0, data=result or [])


@router.get(
    "/subjects/{subject_id}/options",
    response_model=list[EntOptionsServiceDTO],
    summary="ЕНТ варианты по предмету",
    description="Возвращает ЕНТ варианты для указанного предмета",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_ent_options_by_subject(
    subject_id: int,
    student: StudentDTO = Depends(get_student),
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    log_info(
        "ENT options by subject request",
        user_id=student.id,
        action="get_ent_options_by_subject",
        resource="ent_options",
        subject_id=subject_id,
    )
    result = service.get_ents(to_ent_options_get_service(subject_id, student))
    log_info(
        "ENT options by subject retrieved successfully",
        user_id=student.id,
        action="get_ent_options_by_subject",
        resource="ent_options",
        subject_id=subject_id,
        count=len(result) if result else 0,
    )
    if not result:
        return Response(status_code=204)
    return result


@router.post(
    "/attempts/create",
    response_model=EntAttemptServiceDTO,
    summary="Начать ЕНТ попытку",
    description="Создаёт новую попытку прохождения ЕНТ",
    responses={
        **get_common_responses("create"),
        **get_error_responses(EntOptionsDoesntExist, QuestionNotFound),
    },
)
async def create_ent_attempt(
    attempt_data: StartAttemptRequestDTO,
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    locale: str = Depends(get_locale),
    _=Depends(require_active_subscription()),
):
    log_info(
        "ENT attempt creation request",
        user_id=student.id,
        action="create_ent_attempt",
        resource="ent_attempt",
        ent_option_id=attempt_data.ent_option_id,
        locale=locale,
    )
    result = service.create(
        to_ent_attempt_create_dto_service(attempt_data, student),
        locale=locale,
    )

    log_info(
        "ENT attempt created successfully",
        user_id=student.id,
        action="create_ent_attempt",
        resource="ent_attempt",
        attempt_id=getattr(result, "id", "unknown"),
    )
    return result


@router.get(
    "/subject-combinations",
    response_model=list[SubjectCombinationResponseDTO],
    summary="Получить связки предметов",
    description="Возвращает список связок профильных предметов для полноценного экзамена",
    responses={**get_common_responses("read")},
)
async def get_subject_combinations(
    student: StudentDTO = Depends(get_student),
    service: SubjectCombinationService = Depends(get_subject_combination_service),
    # _=Depends(require_active_subscription()),
):
    """Получить все доступные связки предметов для полноценного экзамена"""
    log_info(
        "Subject combinations request",
        user_id=student.id,
        action="get_subject_combinations",
        resource="subject_combinations",
    )

    response = service.get_all()

    log_info(
        "Subject combinations retrieved successfully",
        user_id=student.id,
        action="get_subject_combinations",
        resource="subject_combinations",
        count=len(response),
    )
    return response


@router.post(
    "/attempts/create-full-exam",
    response_model=EntAttemptServiceDTO,
    summary="Начать полноценный экзамен ЕНТ",
    description="Создаёт новую попытку полноценного экзамена из 4 предметов (240 минут)",
    responses={
        **get_common_responses("create"),
        **get_error_responses(EntOptionsDoesntExist, QuestionNotFound),
    },
)
async def create_full_exam_attempt(
    exam_data: StartFullExamRequestDTO,
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    locale: str = Depends(get_locale),
    _=Depends(require_active_subscription()),
):
    from datetime import datetime

    from quiz.dtos.ent_attempts import EntAttemptCreateServiceDTO
    from quiz.dtos.enums import ExamType

    log_info(
        "Full exam attempt creation request",
        user_id=student.id,
        action="create_full_exam_attempt",
        resource="ent_attempt",
        subject_combination_id=exam_data.subject_combination_id,
        locale=locale,
    )

    # Создаём DTO для полноценного экзамена
    attempt_params = EntAttemptCreateServiceDTO(
        student_guid=student.id,
        exam_type=ExamType.full_exam,
        subject_combination_id=exam_data.subject_combination_id,
        started_at=datetime.now(UTC),
    )

    result = service.create(attempt_params, locale=locale)

    log_info(
        "Full exam attempt created successfully",
        user_id=student.id,
        action="create_full_exam_attempt",
        resource="ent_attempt",
        attempt_id=getattr(result, "id", "unknown"),
    )
    return result


@router.post(
    "/attempts/answer",
    response_model=EntAttemptStatisticServiceDTO,
    summary="Ответить на вопросы ЕНТ",
    description="Отправляет ответы на вопросы ЕНТ попытки",
    responses={
        **get_common_responses("create"),
        **get_error_responses(AlreadyAnswered, TrainerAttemptNotExist, WrongStudent, VariantNotExist),
    },
)
async def answer_ent_attempt(
    answer_data: EntAttemptAnswerRequestDTO,
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "ENT attempt answer request",
        user_id=student.id,
        action="answer_ent_attempt",
        resource="ent_attempt",
        attempt_id=answer_data.ent_attempt_id,
        question_count=len(answer_data.questions),
    )

    result = service.answer(to_ent_attempt_answer(answer_data, student))

    log_info(
        "ENT attempt answered successfully",
        user_id=student.id,
        action="answer_ent_attempt",
        resource="ent_attempt",
        attempt_id=answer_data.ent_attempt_id,
    )
    return result


class UpdateQuestionIndexRequest(BaseModel):
    """Запрос на обновление текущей позиции в экзамене"""

    attempt_id: int
    current_question_index: int


@router.patch(
    "/attempts/update-position",
    response_model=UpdateQuestionIndexResponseDTO,
    summary="Обновить позицию в экзамене",
    description="Сохраняет текущую позицию пользователя в экзамене (на каком вопросе остановился)",
    responses={
        **get_common_responses("update"),
        **get_error_responses(AlreadyAnswered, TrainerAttemptNotExist, WrongStudent),
    },
    deprecated=True,
)
async def update_question_position(
    request: UpdateQuestionIndexRequest,
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Update question position request",
        user_id=student.id,
        action="update_question_position",
        resource="ent_attempt",
        attempt_id=request.attempt_id,
        question_index=request.current_question_index,
    )

    result = service.update_current_question_index(
        attempt_id=request.attempt_id,
        student_guid=student.id,
        question_index=request.current_question_index,
    )

    log_info(
        "Question position updated successfully",
        user_id=student.id,
        action="update_question_position",
        resource="ent_attempt",
        attempt_id=request.attempt_id,
        question_index=request.current_question_index,
    )
    return result


@router.get(
    "/attempts",
    response_model=list[EntAttemptHistoryItemDTO],
    summary="История попыток ЕНТ",
    description="Возвращает историю всех попыток студента (by_subject и full_exam)",
    responses={**get_common_responses("read")},
)
async def get_attempts_history(
    limit: int | None = Query(None, ge=1, le=100, description="Лимит записей"),
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Get attempts history request",
        user_id=student.id,
        action="get_attempts_history",
        resource="ent_attempts",
        limit=limit,
    )

    result = service.get_attempts_history(student.id, limit)

    log_info(
        "Attempts history retrieved successfully",
        user_id=student.id,
        action="get_attempts_history",
        resource="ent_attempts",
        count=len(result),
    )
    return result


@router.get(
    "/attempts/{attempt_id}",
    response_model=EntAttemptDetailWithAnswersDTO,
    summary="Детали попытки ЕНТ",
    description="Возвращает детальную информацию о попытке с ответами пользователя и правильными ответами",
    responses=get_ent_responses("read"),
)
async def get_attempt_detail(
    attempt_id: int,
    student: StudentDTO = Depends(get_student),
    service: EntAttemptServiceInterface = Depends(get_ent_attempts_service),
    locale: str = Depends(get_locale),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Get attempt detail request",
        user_id=student.id,
        action="get_attempt_detail",
        resource="ent_attempt",
        attempt_id=attempt_id,
        locale=locale,
    )

    result = service.get_attempt_detail(attempt_id, student.id, locale=locale)

    log_info(
        "Attempt detail retrieved successfully",
        user_id=student.id,
        action="get_attempt_detail",
        resource="ent_attempt",
        attempt_id=attempt_id,
    )
    return result
