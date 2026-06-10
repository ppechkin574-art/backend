"""Admin endpoints for the mobile force-update config.

Single singleton row (per-platform `min_build` + `store_url`). The public
`GET /app/update-config` reads it; here the admin edits it WITHOUT a
backend redeploy.

Endpoints (gated by `allow_only_admins`):
- GET /admin/app-update-config — current values
- PUT /admin/app-update-config — partial update (all fields optional)

The route owns the commit (mirrors leaderboard-prizes): the service
flushes, the route commits after a successful save.
"""

from fastapi import APIRouter, Depends

from api.dependencies import allow_only_admins, get_app_update_config_service
from auth.dtos import UserDTO
from quiz.dtos.app_update_config import (
    AppUpdateConfigDTO,
    AppUpdateConfigUpdateDTO,
)
from quiz.services.app_update_config import AppUpdateConfigService

router = APIRouter(
    prefix="/admin/app-update-config",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get(
    "",
    response_model=AppUpdateConfigDTO,
    summary="Текущий конфиг force-update",
)
def get_config(
    service: AppUpdateConfigService = Depends(get_app_update_config_service),
):
    return AppUpdateConfigDTO.model_validate(service.get())


@router.put(
    "",
    response_model=AppUpdateConfigDTO,
    summary="Изменить конфиг force-update",
)
def update_config(
    body: AppUpdateConfigUpdateDTO,
    admin: UserDTO = Depends(allow_only_admins),
    service: AppUpdateConfigService = Depends(get_app_update_config_service),
):
    config = service.update(body, updated_by=admin.email or str(admin.id))
    service.repo.db.commit()
    return AppUpdateConfigDTO.model_validate(config)
