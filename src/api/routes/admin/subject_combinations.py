from fastapi import APIRouter, Depends
from starlette import status

from api.dependencies import allow_read_or_admin_write, get_subject_combination_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.dtos import (
    DeleteResponseDTO,
    SubjectCombinationCreateRequestDTO,
    SubjectCombinationResponseDTO,
    SubjectCombinationUpdateRequestDTO,
)
from quiz.exceptions import (
    EntOptionsDoesntExist,
    SubjectNotFound,
)
from quiz.services.subject_combinations import SubjectCombinationService

router = APIRouter(
    prefix="/admin/subject-combinations",
    tags=["Admin - Subject Combinations"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get(
    "",
    response_model=list[SubjectCombinationResponseDTO],
    summary="Получить все связки предметов",
    description="Возвращает список всех связок профильных предметов для полноценного экзамена",
    responses={**get_common_responses("read")},
)
async def get_all_subject_combinations(
    service: SubjectCombinationService = Depends(get_subject_combination_service),
):
    """Получить все связки предметов"""
    return service.get_all()


@router.get(
    "/{combination_id}",
    response_model=SubjectCombinationResponseDTO,
    summary="Получить связку предметов",
    description="Возвращает детальную информацию о связке предметов",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_subject_combination(
    combination_id: int,
    service: SubjectCombinationService = Depends(get_subject_combination_service),
):
    """Получить конкретную связку предметов"""
    return service.get_by_id(combination_id)


@router.post(
    "",
    response_model=SubjectCombinationResponseDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Создать связку предметов",
    description="Создание новой связки профильных предметов",
    responses={
        **get_common_responses("create"),
        **get_error_responses(SubjectNotFound),
    },
)
async def create_subject_combination(
    data: SubjectCombinationCreateRequestDTO,
    service: SubjectCombinationService = Depends(get_subject_combination_service),
):
    """Создать новую связку предметов"""
    return service.create(data)


@router.patch(
    "/{combination_id}",
    response_model=SubjectCombinationResponseDTO,
    summary="Обновить связку предметов",
    description="Обновление существующей связки профильных предметов",
    responses={
        **get_common_responses("update"),
        **get_error_responses(EntOptionsDoesntExist, SubjectNotFound),
    },
)
async def update_subject_combination(
    combination_id: int,
    data: SubjectCombinationUpdateRequestDTO,
    service: SubjectCombinationService = Depends(get_subject_combination_service),
):
    """Обновить связку предметов"""
    return service.update(combination_id, data)


@router.delete(
    "/{combination_id}",
    response_model=DeleteResponseDTO,
    summary="Удалить связку предметов",
    description="Удаление связки профильных предметов",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def delete_subject_combination(
    combination_id: int,
    service: SubjectCombinationService = Depends(get_subject_combination_service),
):
    """Удалить связку предметов"""
    message = service.delete(combination_id)
    return DeleteResponseDTO(message=message)
