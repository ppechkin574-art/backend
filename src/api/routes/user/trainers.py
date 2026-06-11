from fastapi import APIRouter, Depends

from api.dependencies import (
    get_progress_service,
    get_question_service,
    get_student,
    get_trainer_attempt_service,
    get_user,
    require_active_subscription,
)
from api.middlewares.locale import get_locale
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import to_test_answer_dto, to_test_create_dto
from api.routes.quiz.dtos import (
    QuizAnswerDTO,
    QuizCreateRequestDTO,
    TopicWithTrainersResponseDTO,
)
from quiz.dtos.trainer_attempts import (
    FinishAttemptResponseDTO,
    TrainerAttemptAnswerResponseDTO,
    TrainerAttemptDetailDTO,
    TrainerAttemptPublicDTO,
    TrainerAttemptResultDTO,
)
from quiz.exceptions import (
    AttemptCompleted,
    AttemptNotCompleted,
    NoQuestionsInTrainerAttempt,
    TestQuestionNotExist,
    TopicNotFound,
    TrainerAttemptNotExist,
    TrainerNotFound,
    VariantNotExist,
)
from quiz.services import TrainerAttemptServiceInterface
from quiz.services.progress import ProgressService
from quiz.services.questions import QuestionServiceInterface
from student import StudentDTO
from utils.monitoring import log_info

router = APIRouter(prefix="/user/trainers", tags=["User - Trainers"], dependencies=[Depends(get_user)])


@router.get(
    "/subjects/{subject_id}",
    response_model=TopicWithTrainersResponseDTO,
    summary="Тренажёры по предмету",
    description="Возвращает темы и тренажёры для указанного предмета",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFound, TrainerNotFound),
    },
)
async def get_trainers_by_subject(
    subject_id: int,
    student: StudentDTO = Depends(get_student),
    service: QuestionServiceInterface = Depends(get_question_service),
    progress_service: ProgressService = Depends(get_progress_service),
):
    log_info(
        "Trainers by subject request",
        user_id=student.id,
        action="get_trainers_by_subject",
        resource="trainers",
        subject_id=subject_id,
    )

    result = service.get_trainers_by_subject(subject_id, student.id)

    for topic in result:
        for trainer in topic["trainers"]:
            progress = progress_service.get_trainer_progress(str(student.id), trainer["id"])
            trainer["progress"] = progress

            # Get user's attempts for this trainer
            attempts = []
            try:
                if hasattr(progress_service, "_uow") and hasattr(
                    progress_service._uow.trainer_attempts, "get_user_trainer_attempts"
                ):
                    with progress_service._uow:
                        attempt_objects = progress_service._uow.trainer_attempts.get_user_trainer_attempts(
                            str(student.id), trainer["id"]
                        )
                        attempts = [attempt.id for attempt in attempt_objects]
            except Exception as e:
                log_info(
                    "Error getting trainer attempts",
                    user_id=student.id,
                    trainer_id=trainer["id"],
                    error=str(e),
                )
            trainer["attempt_ids"] = attempts

    log_info(
        "Trainers by subject retrieved successfully",
        user_id=student.id,
        action="get_trainers_by_subject",
        resource="trainers",
        subject_id=subject_id,
        topic_count=len(result),
    )
    return TopicWithTrainersResponseDTO(count=len(result), data=result)


@router.get(
    "/attempts/{attempt_id}",
    response_model=TrainerAttemptResultDTO,
    summary="Получить результаты попытки тренажера",
    description="Возвращает детальную информацию о завершенной попытке тренажера",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TrainerAttemptNotExist, AttemptNotCompleted),
    },
)
async def get_attempt_result(
    attempt_id: int,
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
    student: StudentDTO = Depends(get_student),
):
    full_result = service.get_attempt_result(attempt_id, student.id)
    return TrainerAttemptResultDTO(
        attempt_id=full_result.attempt_id,
        trainer_id=full_result.trainer_id,
        started_at=full_result.started_at,
        completed_at=full_result.completed_at,
        score=full_result.score or 0,
        correct_answers=full_result.correct_answers,
        incorrect_answers=full_result.incorrect_answers,
        max_score=full_result.max_score,
    )


@router.get(
    "/attempts/{attempt_id}/details",
    response_model=TrainerAttemptDetailDTO,
    summary="Детальная информация о попытке тренажера",
    description="Возвращает полную информацию о завершенной попытке: вопросы, варианты, ответы пользователя, подсказки и т.д.",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TrainerAttemptNotExist, AttemptNotCompleted),
    },
)
async def get_attempt_details(
    attempt_id: int,
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
    student: StudentDTO = Depends(get_student),
):
    log_info(
        "Trainer attempt details request",
        user_id=student.id,
        action="get_attempt_details",
        resource="trainer_attempt",
        attempt_id=attempt_id,
    )
    result = service.get_attempt_details(attempt_id, student.id)
    log_info(
        "Trainer attempt details retrieved successfully",
        user_id=student.id,
        action="get_attempt_details",
        resource="trainer_attempt",
        attempt_id=attempt_id,
    )
    return result


@router.post(
    "/attempts/create",
    response_model=TrainerAttemptPublicDTO,
    summary="Начать тренажёр",
    description="Создаёт новую попытку прохождения тренажёра",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TopicNotFound, NoQuestionsInTrainerAttempt, TrainerNotFound),
    },
)
async def create_trainer_attempt(
    quiz_data: QuizCreateRequestDTO,
    student: StudentDTO = Depends(get_student),
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
    locale: str = Depends(get_locale),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Trainer attempt creation request",
        user_id=student.id,
        action="create_trainer_attempt",
        resource="trainer_attempt",
        topic_id=quiz_data.topic_id,
        locale=locale,
    )

    test_create = to_test_create_dto(student, quiz_data)
    result = service.create(test_create, locale=locale)

    log_info(
        "Trainer attempt created successfully",
        user_id=student.id,
        action="create_trainer_attempt",
        resource="trainer_attempt",
        attempt_id=getattr(result, "id", "unknown"),
    )
    data = result.model_dump(exclude={"questions": {"__all__": {"variants": {"__all__": {"is_correct"}}}}})
    return TrainerAttemptPublicDTO(**data)


@router.post(
    "/attempts/{trainer_attempt_question_id}/answer",
    response_model=TrainerAttemptAnswerResponseDTO,
    summary="Ответить на вопрос тренажёра",
    description="Отправляет ответ на вопрос в текущей попытке тренажёра",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TestQuestionNotExist, VariantNotExist, AttemptCompleted),
    },
)
async def answer_trainer_question(
    trainer_attempt_question_id: int,
    answer_data: QuizAnswerDTO,
    student: StudentDTO = Depends(get_student),
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Trainer question answer request",
        user_id=student.id,
        action="answer_trainer_question",
        resource="trainer_attempt",
        trainer_attempt_question_id=trainer_attempt_question_id,
        variant_ids=answer_data.variants,
    )

    answer_dto = to_test_answer_dto(student, answer_data, trainer_attempt_question_id)
    result = service.answer(answer_dto)

    log_info(
        "Trainer question answered successfully",
        user_id=student.id,
        action="answer_trainer_question",
        resource="trainer_attempt",
        trainer_attempt_question_id=trainer_attempt_question_id,
        is_correct=getattr(result, "is_correct", False),
    )
    return result


@router.post(
    "/attempts/{trainer_attempt_id}/complete",
    response_model=FinishAttemptResponseDTO,
    summary="Завершить попытку тренажёра",
    description="Завершает текущую попытку прохождения тренажёра и возвращает результаты",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TrainerAttemptNotExist, AttemptCompleted),
    },
)
async def complete_trainer_attempt(
    trainer_attempt_id: int,
    student: StudentDTO = Depends(get_student),
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Trainer attempt completion request",
        user_id=student.id,
        action="complete_trainer_attempt",
        resource="trainer_attempt",
        trainer_attempt_id=trainer_attempt_id,
    )

    result = service.finish_attempt(trainer_attempt_id, student.id)

    log_info(
        "Trainer attempt completed successfully",
        user_id=student.id,
        action="complete_trainer_attempt",
        resource="trainer_attempt",
        trainer_attempt_id=trainer_attempt_id,
        correct_answers=getattr(result, "correct_answers", 0),
        total_questions=getattr(result, "total_questions", 0),
    )
    return result


@router.get(
    "/{trainer_id}/last-completed-statistics",
    response_model=TrainerAttemptDetailDTO,
    summary="Статистика последней завершенной попытки тренажера",
    description="Возвращает детальную статистику последней завершенной попытки для указанного тренажера",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TrainerAttemptNotExist, TrainerNotFound),
    },
)
async def get_last_completed_trainer_statistics(
    trainer_id: int,
    student: StudentDTO = Depends(get_student),
    service: TrainerAttemptServiceInterface = Depends(get_trainer_attempt_service),
):
    log_info(
        "Last completed trainer statistics request",
        user_id=student.id,
        action="get_last_completed_trainer_statistics",
        resource="trainer_attempt",
        trainer_id=trainer_id,
    )

    result = service.get_last_completed_attempt_statistics(trainer_id, student.id)

    log_info(
        "Last completed trainer statistics retrieved successfully",
        user_id=student.id,
        action="get_last_completed_trainer_statistics",
        resource="trainer_attempt",
        trainer_id=trainer_id,
        attempt_id=result.id,
    )
    return result
