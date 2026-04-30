import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    get_module_lesson_service,
    get_subject_module_service,
    get_user,
    require_active_subscription,
)
from auth.dtos.users import UserDTO
from quiz.dtos.modules import (
    ModuleLessonResponseDTO,
    ModuleLessonWithContentDTO,
    SubjectModuleDTO,
    SubjectModulesResponseDTO,
)
from quiz.exceptions import SubjectNotFoundService
from quiz.services.modules import ModuleLessonService, SubjectModuleService

router = APIRouter(
    prefix="/user/modules",
    tags=["User - Edu Modules"],
    dependencies=[Depends(get_user)],
)

logger = logging.getLogger(__name__)


@router.get(
    "/subjects/{subject_id}",
    response_model=SubjectModulesResponseDTO,
    summary="Get subject modules",
    description="Returns all modules for a subject",
)
async def get_subject_modules(
    subject_id: int,
    user: UserDTO = Depends(get_user),
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get all modules for a subject"""
    try:
        return module_service.get_subject_modules_response(subject_id, user.id)
    except SubjectNotFoundService as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with id {subject_id} not found",
        ) from e
    except Exception as e:
        logger.exception("Error getting subject modules: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.get(
    "/{module_id}",
    response_model=SubjectModuleDTO,
    summary="Get module",
    description="Returns a module by ID",
)
async def get_module(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get module by ID"""
    try:
        return module_service.get_by_id(module_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{module_id}/lessons",
    response_model=list[ModuleLessonResponseDTO],
    summary="Get module lessons",
    description="Returns all lessons for a module",
)
async def get_module_lessons(
    module_id: int,
    user: UserDTO = Depends(get_user),
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
    _=Depends(require_active_subscription()),
):
    """Get all lessons for a module"""
    try:
        return lesson_service.get_module_lessons_with_trainers(module_id, user.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/lessons/{lesson_id}",
    response_model=ModuleLessonWithContentDTO,
    summary="Get lesson by ID",
    description="Returns a lesson by ID",
)
async def get_lesson(
    lesson_id: int,
    user: UserDTO = Depends(get_user),
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
    _=Depends(require_active_subscription()),
):
    """Get lesson by ID"""
    try:
        return lesson_service.get_with_details(lesson_id, user.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
