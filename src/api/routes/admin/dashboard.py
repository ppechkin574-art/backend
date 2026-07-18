import logging

from fastapi import APIRouter, Depends

from api.dependencies import allow_read_or_admin_write, get_admin_service
from api.exceptions.documentation import get_common_responses
from quiz.dtos.admin import AdminDashboardDTO
from quiz.services.admin import AdminService

router = APIRouter(
    prefix="/admin/dashboard",
    tags=["Admin - Dashboard"],
    dependencies=[Depends(allow_read_or_admin_write)],
)

logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=AdminDashboardDTO,
    summary="Получить дашборд",
    description="Возвращает все данные для админской панели",
    responses={
        **get_common_responses("read"),
    },
)
async def get_admin_dashboard(admin_service: AdminService = Depends(get_admin_service)):
    return admin_service.get_admin_dashboard()


@router.get("/subjects")
async def get_dashboard_subjects(
    admin_service: AdminService = Depends(get_admin_service),
):
    return {"subjects": admin_service.get_admin_dashboard().subjects}


@router.get("/topics")
async def get_dashboard_topics(
    admin_service: AdminService = Depends(get_admin_service),
):
    return {"topics": admin_service.get_admin_dashboard().topics}


@router.get("/summary")
async def get_dashboard_summary(
    admin_service: AdminService = Depends(get_admin_service),
):
    return {"total_stats": admin_service.get_admin_dashboard().total_stats}
