from fastapi import APIRouter, Depends, HTTPException

from api.common import ListDTO, ListQueryDTO
from api.dependencies import allow_read_or_admin_write, get_topic_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import to_topic_create_service, to_topic_update_service
from api.routes.quiz.dtos import (
    DeleteResponseDTO,
    MergeResponseDTO,
    TopicCreateRequestDTO,
    TopicUpdateRequestDTO,
)
from quiz.dtos.topic import TopicServiceDTO, TopicWithStatsDTO
from quiz.exceptions import (
    TopicAlreadyExists,
    TopicIdViolatesNotNullService,
    TopicNotFoundService,
    TopicSameNameService,
    TopicSubjectNotFoundService,
)
from quiz.services.topics import TopicServiceInterface

router = APIRouter(
    prefix="/admin/topics",
    tags=["Admin - Topics"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get(
    "",
    response_model=ListDTO[TopicServiceDTO],
    summary="Получить темы",
    description="Возвращает список тем с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFoundService),
    },
)
async def get_admin_topics(
    query: ListQueryDTO = Depends(),
    service: TopicServiceInterface = Depends(get_topic_service),
):
    topics, total_count = service.list(
        page=query.page,
        page_size=query.page_size,
        search=query.search,
        sort_by=query.sort_columns[0] if query.sort_columns else None,
        sort_order=("asc" if (query.is_sort_ascendings and query.is_sort_ascendings[0]) else "desc"),
    )

    return ListDTO[TopicServiceDTO](
        draw=query.draw,
        records_total=total_count,
        records_filtered=total_count,
        data=topics,
    )


@router.get(
    "/with-stats",
    response_model=list[TopicWithStatsDTO],
    summary="Темы со статистикой",
    description="Возвращает темы со статистикой вопросов",
    responses={
        **get_common_responses("read"),
    },
)
async def get_topics_with_stats(
    service: TopicServiceInterface = Depends(get_topic_service),
):
    topics_with_counts = service.get_with_question_counts()
    return [
        TopicWithStatsDTO(
            id=topic["topic"].id,
            subject_id=topic["topic"].subject_id,
            name=topic["topic"].name,
            question_count=topic["question_count"],
        )
        for topic in topics_with_counts
    ]


@router.get(
    "/{topic_id}",
    response_model=TopicServiceDTO,
    summary="Получить тему по ID",
    description="Возвращает детальную информацию о теме",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TopicNotFoundService),
    },
)
async def get_admin_topic_by_id(
    topic_id: int,
    service: TopicServiceInterface = Depends(get_topic_service),
):
    if topic := service.get_by_id(topic_id):
        return topic
    else:
        raise HTTPException(status_code=404, detail="Topic not found")


@router.post(
    "",
    response_model=TopicServiceDTO,
    status_code=201,
    summary="Создать тему",
    description="Создание новой темы (только для администраторов)",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TopicSubjectNotFoundService, TopicSameNameService, TopicAlreadyExists),
    },
)
async def create_topic(
    topic_data: TopicCreateRequestDTO,
    service: TopicServiceInterface = Depends(get_topic_service),
):
    return service.create(to_topic_create_service(topic_data))


@router.patch(
    "/{topic_id}",
    response_model=TopicServiceDTO,
    summary="Обновить тему",
    description="Частичное обновление темы",
    responses={
        **get_common_responses("update"),
        **get_error_responses(TopicNotFoundService, TopicSubjectNotFoundService, TopicSameNameService),
    },
)
async def update_topic(
    topic_id: int,
    topic_data: TopicUpdateRequestDTO,
    service: TopicServiceInterface = Depends(get_topic_service),
):
    return service.update(topic_id, to_topic_update_service(topic_data))


@router.delete(
    "/{topic_id}",
    response_model=DeleteResponseDTO,
    summary="Удалить тему",
    description="Удаление темы",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(TopicNotFoundService, TopicIdViolatesNotNullService),
    },
)
async def delete_topic(
    topic_id: int,
    service: TopicServiceInterface = Depends(get_topic_service),
):
    service.delete(topic_id)
    return DeleteResponseDTO(message="Topic deleted successfully")


@router.post(
    "/merge",
    response_model=MergeResponseDTO,
    summary="Объединить темы",
    description="Объединение двух тем",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TopicNotFoundService),
    },
)
async def merge_topics(
    source_topic_id: int,
    target_topic_id: int,
    service: TopicServiceInterface = Depends(get_topic_service),
):
    result = service.merge_topics(source_topic_id, target_topic_id)
    merged_entity_dict = {
        "id": result.id,
        "name": result.name,
        "subject_id": result.subject_id,
    }
    return MergeResponseDTO(
        message="Topics merged successfully",
        merged_entity=merged_entity_dict,
        source_id=source_topic_id,
        target_id=target_topic_id,
    )
