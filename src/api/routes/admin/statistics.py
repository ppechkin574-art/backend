import logging

from fastapi import APIRouter, Depends

from api.dependencies import allow_read_or_admin_write, get_admin_service
from api.exceptions.documentation import get_common_responses
from quiz.dtos.admin import (
    AdminSubjectDTO,
    AdminTopicDTO,
    AdminTrainerDTO,
)
from quiz.services.admin import AdminService

router = APIRouter(
    prefix="/admin/statistics",
    tags=["Admin - Statistics"],
    dependencies=[Depends(allow_read_or_admin_write)],
)

logger = logging.getLogger(__name__)


@router.get(
    "/subjects",
    response_model=list[AdminSubjectDTO],
    summary="Статистика по предметам",
    description="Возвращает предметы с полной статистикой",
    responses={
        **get_common_responses("read"),
    },
)
async def get_admin_subjects(
    admin_service: AdminService = Depends(get_admin_service),
):
    return admin_service.get_admin_dashboard().subjects


@router.get(
    "/topics",
    response_model=list[AdminTopicDTO],
    summary="Статистика по темам",
    description="Возвращает темы с полной статистикой",
    responses={
        **get_common_responses("read"),
    },
)
async def get_admin_topics(
    admin_service: AdminService = Depends(get_admin_service),
):
    return admin_service.get_admin_dashboard().topics


@router.get(
    "/trainers",
    response_model=list[AdminTrainerDTO],
    summary="Статистика по тренажёрам",
    description="Возвращает тренажёры с полной статистикой",
    responses={
        **get_common_responses("read"),
    },
)
async def get_admin_trainers(
    admin_service: AdminService = Depends(get_admin_service),
):
    return admin_service.get_admin_dashboard().trainers


@router.get(
    "/ents",
    summary="Статистика по ЕНТ вариантам",
    description="Возвращает ЕНТ варианты с количеством вопросов",
    responses={
        **get_common_responses("read"),
    },
)
async def get_admin_ents(
    admin_service: AdminService = Depends(get_admin_service),
):
    return {"ent_options": admin_service.get_admin_dashboard().ent_options}
