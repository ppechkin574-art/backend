from fastapi import APIRouter, Depends

from api.dependencies import allow_only_admins, get_trainer_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.dtos import (
    DeleteResponseDTO,
    TrainerCreateRequestDTO,
    TrainerUpdateRequestDTO,
)
from quiz.dtos.trainers import (
    TrainerCreateServiceDTO,
    TrainerServiceDTO,
    TrainerUpdateServiceDTO,
    TrainerWithQuestionsDTO,
    TrainerWithStatsDTO,
)
from quiz.exceptions import TopicNotFound, TrainerNotFound
from quiz.services.trainers import TrainerServiceInterface

router = APIRouter(
    prefix="/admin/trainers",
    tags=["Admin - Trainers"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get(
    "",
    response_model=list[TrainerWithStatsDTO],
    summary="Получить тренажёры",
    description="Возвращает все тренажёры со статистикой",
    responses={
        **get_common_responses("read"),
    },
)
async def get_all_trainers(
    service: TrainerServiceInterface = Depends(get_trainer_service),
):
    trainers_with_stats = service.get_all_trainers_with_question_counts()
    return [
        TrainerWithStatsDTO(
            id=trainer.id,
            guid=trainer.guid,
            name=trainer.name,
            topic_id=trainer.topic_id,
            question_count=count,
        )
        for trainer, count in trainers_with_stats
    ]


@router.post(
    "/create",
    response_model=TrainerServiceDTO,
    status_code=201,
    summary="Создать тренажёр",
    description="Создание нового тренажёра",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TopicNotFound),
    },
)
async def create_trainer(
    trainer_data: TrainerCreateRequestDTO,
    service: TrainerServiceInterface = Depends(get_trainer_service),
):
    return service.create(TrainerCreateServiceDTO(**trainer_data.model_dump()))


@router.get(
    "/{trainer_id}",
    response_model=TrainerWithQuestionsDTO,
    summary="Получить тренажёр с вопросами",
    description="Возвращает детальную информацию о тренажёре",
    responses={
        **get_common_responses("read"),
        **get_error_responses(TrainerNotFound),
    },
)
async def get_trainer_details(
    trainer_id: int,
    service: TrainerServiceInterface = Depends(get_trainer_service),
):
    return service.get_trainer_with_questions(trainer_id)


@router.patch(
    "/{trainer_id}",
    response_model=TrainerServiceDTO,
    summary="Обновить тренажёр",
    description="Частичное обновление тренажёра",
    responses={
        **get_common_responses("update"),
        **get_error_responses(TrainerNotFound, TopicNotFound),
    },
)
async def update_trainer(
    trainer_id: int,
    trainer_data: TrainerUpdateRequestDTO,
    service: TrainerServiceInterface = Depends(get_trainer_service),
):
    return service.update(trainer_id, TrainerUpdateServiceDTO(**trainer_data.model_dump()))


@router.delete(
    "/{trainer_id}",
    response_model=DeleteResponseDTO,
    summary="Удалить тренажёр",
    description="Удаление тренажёра",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(TrainerNotFound),
    },
)
async def delete_trainer(
    trainer_id: int,
    service: TrainerServiceInterface = Depends(get_trainer_service),
):
    service.delete(trainer_id)
    return DeleteResponseDTO(message="Trainer deleted successfully")
