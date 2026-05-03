from fastapi import APIRouter, Depends, Query

from api.dependencies import (
    get_question_service,
    get_subject_service,
    get_user,
    require_active_subscription,
)
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import to_subject_with_questions_response
from auth.dtos.users import UserDTO
from quiz.dtos.progress import (
    SubjectProgressDTO,
    TopicProgressDTO,
)
from quiz.dtos.subject import SubjectServiceDTO, SubjectServiceResponceDTO
from quiz.dtos.topic import TopicServiceDTO
from quiz.exceptions import QuestionNotFound, SubjectNotFound, TopicNotFound
from quiz.services.questions import QuestionServiceInterface
from quiz.services.subjects import SubjectServiceInterface
from utils.monitoring import log_info

router = APIRouter(prefix="/user/subjects", tags=["User - Subjects"], dependencies=[Depends(get_user)])


@router.get(
    "",
    response_model=SubjectServiceResponceDTO,
    summary="Получить предметы",
    description="Возвращает список предметов с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFound),
    },
)
async def get_subjects(
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
    search: str | None = Query(None, description="Поисковая строка"),
    service: SubjectServiceInterface = Depends(get_subject_service),
    user: UserDTO = Depends(get_user),
):
    log_info(
        "Subjects list request",
        user_id=user.id,
        action="get_subjects",
        resource="subjects",
        page=page,
        page_size=page_size,
        search=search,
    )

    subjects, total_count = service.list(page=page, page_size=page_size, search=search)

    log_info(
        "Subjects list retrieved successfully",
        user_id=user.id,
        action="get_subjects",
        resource="subjects",
        count=len(subjects),
        total_count=total_count,
    )
    return SubjectServiceResponceDTO(count=total_count, data=subjects)


@router.get(
    "/with-progress",
    response_model=list[SubjectProgressDTO],
    summary="Получить предметы с прогрессом",
    description="Возвращает список предметов с прогрессом пользователя (0.0 - 1.0)",
)
async def get_subjects_with_progress(
    only_correct: bool = Query(True, description="Учитывать только правильно решенные вопросы"),
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
    # _=Depends(require_active_subscription()),
):
    """Получить все предметы с прогрессом"""
    log_info(
        "Subjects with progress request",
        user_id=user.id,
        action="get_subjects_with_progress",
        resource="subjects",
    )

    subjects = service.get_subjects_with_progress(user.id, only_correct)

    log_info(
        "Subjects with progress retrieved successfully",
        user_id=user.id,
        action="get_subjects_with_progress",
        resource="subjects",
        count=len(subjects),
    )

    return subjects


@router.get(
    "/{subject_id}",
    response_model=SubjectServiceDTO,
    summary="Получить предмет по ID",
    description="Возвращает детальную информацию о предмете",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFound, TopicNotFound),
    },
)
async def get_subject_by_id(
    subject_id: int,
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    log_info(
        "Subject details request",
        user_id=user.id,
        action="get_subject_by_id",
        resource="subjects",
        subject_id=subject_id,
    )

    result = service.get_by_id(subject_id)

    log_info(
        "Subject details retrieved successfully",
        user_id=user.id,
        action="get_subject_by_id",
        resource="subjects",
        subject_id=subject_id,
    )
    return result


@router.get(
    "/{subject_id}/with-progress",
    response_model=SubjectProgressDTO,
    summary="Получить предмет с прогрессом",
    description="Возвращает предмет с прогрессом пользователя (0.0 - 1.0)",
)
async def get_subject_with_progress(
    subject_id: int,
    only_correct: bool = Query(True, description="Учитывать только правильно решенные вопросы"),
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
    # _=Depends(require_active_subscription()),
):
    """Получить предмет с прогрессом"""
    log_info(
        "Subject with progress request",
        user_id=user.id,
        action="get_subject_with_progress",
        resource="subjects",
        subject_id=subject_id,
    )

    # Получаем предмет
    subject = service.get_by_id(subject_id)

    # Получаем прогресс по предмету
    progress = service.get_subject_progress(subject_id, user.id, only_correct)

    result = SubjectProgressDTO(
        id=subject.id,
        name=subject.name,
        type=subject.type,
        image=subject.image,
        progress=progress,
    )

    log_info(
        "Subject with progress retrieved successfully",
        user_id=user.id,
        action="get_subject_with_progress",
        resource="subjects",
        subject_id=subject_id,
    )

    return result


@router.get(
    "/{subject_id}/topics",
    response_model=list[TopicServiceDTO],
    summary="Получить темы предмета",
    description="Возвращает все темы для указанного предмета",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFound, TopicNotFound),
    },
)
async def get_subject_topics(
    subject_id: int,
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
    # _=Depends(require_active_subscription()),
):
    log_info(
        "Subject topics request",
        user_id=user.id,
        action="get_subject_topics",
        resource="subjects",
        subject_id=subject_id,
    )

    result = service.get_topics(subject_id)

    log_info(
        "Subject topics retrieved successfully",
        user_id=user.id,
        action="get_subject_topics",
        resource="subjects",
        subject_id=subject_id,
        topic_count=len(result),
    )
    return result


@router.get(
    "/{subject_id}/topics/with-progress",
    response_model=list[TopicProgressDTO],
    summary="Получить темы предмета с прогрессом",
    description="Возвращает все темы предмета с прогрессом пользователя (0.0 - 1.0)",
)
async def get_subject_topics_with_progress(
    subject_id: int,
    only_correct: bool = Query(True, description="Учитывать только правильно решенные вопросы"),
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
    # _=Depends(require_active_subscription()),
):
    """Получить темы предмета с прогрессом"""
    log_info(
        "Subject topics with progress request",
        user_id=user.id,
        action="get_subject_topics_with_progress",
        resource="subjects",
        subject_id=subject_id,
    )

    result = service.get_topics_with_progress(subject_id, user.id, only_correct)

    log_info(
        "Subject topics with progress retrieved successfully",
        user_id=user.id,
        action="get_subject_topics_with_progress",
        resource="subjects",
        subject_id=subject_id,
        topic_count=len(result),
    )
    return result


@router.get(
    "/{subject_id}/questions",
    summary="Получить вопросы по предмету",
    description="Возвращает вопросы для указанного предмета с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFound, QuestionNotFound),
    },
)
async def get_subject_questions(
    subject_id: int,
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
    question_service: QuestionServiceInterface = Depends(get_question_service),
    subject_service: SubjectServiceInterface = Depends(get_subject_service),
    user: UserDTO = Depends(get_user),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Subject questions request",
        user_id=user.id,
        action="get_subject_questions",
        resource="subjects",
        subject_id=subject_id,
        page=page,
        page_size=page_size,
    )

    subject = subject_service.get_by_id(subject_id)
    questions, total_count = question_service.list(page=page, page_size=page_size, subject_ids=[subject_id])

    log_info(
        "Subject questions retrieved successfully",
        user_id=user.id,
        action="get_subject_questions",
        resource="subjects",
        subject_id=subject_id,
        question_count=len(questions),
        total_count=total_count,
    )

    return to_subject_with_questions_response(subject, questions, total_count)


@router.get(
    "/{subject_id}/stats",
    summary="Статистика предмета",
    description="Возвращает базовую статистику по предмету",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFound),
    },
)
async def get_subject_stats(
    subject_id: int,
    user: UserDTO = Depends(get_user),
    service: SubjectServiceInterface = Depends(get_subject_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Subject stats request",
        user_id=user.id,
        action="get_subject_stats",
        resource="subjects",
        subject_id=subject_id,
    )

    topic_count = service.count_topics(subject_id)
    question_count = service.count_questions_by_subject(subject_id)

    log_info(
        "Subject stats retrieved successfully",
        user_id=user.id,
        action="get_subject_stats",
        resource="subjects",
        subject_id=subject_id,
        topic_count=topic_count,
        question_count=question_count,
    )

    return {
        "subject_id": subject_id,
        "topic_count": topic_count,
        "question_count": question_count,
    }
