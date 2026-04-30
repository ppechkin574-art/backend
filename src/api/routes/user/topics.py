from fastapi import APIRouter, Depends, Query

from api.dependencies import (
    get_question_service,
    get_topic_service,
    get_user,
    require_active_subscription,
)
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import to_topic_with_questions_response
from auth.dtos.users import UserDTO
from quiz.dtos.progress import TopicProgressDTO
from quiz.dtos.topic import TopicServiceDTO, TopicServiceResponceDTO
from quiz.exceptions import QuestionNotFound, TopicNotFound
from quiz.services.questions import QuestionServiceInterface
from quiz.services.topics import TopicServiceInterface
from utils.monitoring import log_info

router = APIRouter(prefix="/user/topics", tags=["User - Topics"], dependencies=[Depends(get_user)])


@router.get(
    "",
    response_model=TopicServiceResponceDTO,
    summary="Получить темы",
    description="Возвращает список тем с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFound),
    },
)
async def get_topics(
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
    search: str | None = Query(None, description="Поисковая строка"),
    subject_id: int | None = Query(None, description="Фильтр по предмету"),
    user: UserDTO = Depends(get_user),
    service: TopicServiceInterface = Depends(get_topic_service),
):
    log_info(
        "Topics list request",
        user_id=user.id,
        action="get_topics",
        resource="topics",
        page=page,
        page_size=page_size,
        search=search,
        subject_id=subject_id,
    )

    if subject_id:
        topics, total_count = service.get_by_subject(subject_id, page, page_size, search)
        log_info(
            "Topics by subject retrieved successfully",
            user_id=user.id,
            action="get_topics",
            resource="topics",
            subject_id=subject_id,
            count=len(topics),
            total_count=total_count,
        )
    else:
        topics, total_count = service.list(page=page, page_size=page_size, search=search)
        log_info(
            "Topics list retrieved successfully",
            user_id=user.id,
            action="get_topics",
            resource="topics",
            count=len(topics),
            total_count=total_count,
        )
    return TopicServiceResponceDTO(count=total_count, data=topics)


@router.get(
    "/{topic_id}",
    response_model=TopicServiceDTO,
    summary="Получить тему по ID",
    description="Возвращает детальную информацию о теме",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFound),
    },
)
async def get_topic_by_id(
    topic_id: int,
    user: UserDTO = Depends(get_user),
    service: TopicServiceInterface = Depends(get_topic_service),
):
    log_info(
        "Topic details request",
        user_id=user.id,
        action="get_topic_by_id",
        resource="topics",
        topic_id=topic_id,
    )

    result = service.get_by_id(topic_id)

    log_info(
        "Topic details retrieved successfully",
        user_id=user.id,
        action="get_topic_by_id",
        resource="topics",
        topic_id=topic_id,
    )
    return result


@router.get(
    "/{topic_id}/with-progress",
    response_model=TopicProgressDTO,
    summary="Получить тему с прогрессом",
    description="Возвращает тему с прогрессом пользователя (0.0 - 1.0)",
)
async def get_topic_with_progress(
    topic_id: int,
    only_correct: bool = Query(True, description="Учитывать только правильно решенные вопросы"),
    user: UserDTO = Depends(get_user),
    topic_service: TopicServiceInterface = Depends(get_topic_service),
    # _=Depends(require_active_subscription()),
):
    """Получить тему с прогрессом"""
    log_info(
        "Topic with progress request",
        user_id=user.id,
        action="get_topic_with_progress",
        resource="topics",
        topic_id=topic_id,
    )

    # Получаем тему
    topic = topic_service.get_by_id(topic_id)

    # Получаем прогресс
    progress = topic_service.get_topic_progress(topic_id, user.id, only_correct)

    result = TopicProgressDTO(
        id=topic.id,
        name=topic.name,
        subject_id=topic.subject_id,
        progress=progress,
    )

    log_info(
        "Topic with progress retrieved successfully",
        user_id=user.id,
        action="get_topic_with_progress",
        resource="topics",
        topic_id=topic_id,
    )

    return result


@router.get(
    "/{topic_id}/questions",
    summary="Получить вопросы по теме",
    description="Возвращает вопросы для указанной темы с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFound, QuestionNotFound),
    },
)
async def get_topic_questions(
    topic_id: int,
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
    user: UserDTO = Depends(get_user),
    question_service: QuestionServiceInterface = Depends(get_question_service),
    topic_service: TopicServiceInterface = Depends(get_topic_service),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Topic questions request",
        user_id=user.id,
        action="get_topic_questions",
        resource="topics",
        topic_id=topic_id,
        page=page,
        page_size=page_size,
    )

    topic = topic_service.get_by_id(topic_id)
    questions, total_count = question_service.list(page=page, page_size=page_size, topic_ids=[topic_id])

    log_info(
        "Topic questions retrieved successfully",
        user_id=user.id,
        action="get_topic_questions",
        resource="topics",
        topic_id=topic_id,
        question_count=len(questions),
        total_count=total_count,
    )

    return to_topic_with_questions_response(topic, questions, total_count)


@router.get(
    "/{topic_id}/stats",
    summary="Статистика темы",
    description="Возвращает базовую статистику по теме",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFound),
    },
)
async def get_topic_stats(
    topic_id: int,
    topic_service: TopicServiceInterface = Depends(get_topic_service),
    question_service: QuestionServiceInterface = Depends(get_question_service),
    user: UserDTO = Depends(get_user),
    _=Depends(require_active_subscription()),
):
    log_info(
        "Topic stats request",
        user_id=user.id,
        action="get_topic_stats",
        resource="topics",
        topic_id=topic_id,
    )

    topic = topic_service.get_by_id(topic_id)
    question_count = question_service.count_questions_by_topic(topic_id)

    log_info(
        "Topic stats retrieved successfully",
        user_id=user.id,
        action="get_topic_stats",
        resource="topics",
        topic_id=topic_id,
        question_count=question_count,
    )

    return {
        "topic_id": topic_id,
        "topic_name": topic.name,
        "subject_id": topic.subject_id,
        "question_count": question_count,
    }
