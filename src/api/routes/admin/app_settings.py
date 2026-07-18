"""Admin endpoints for the `app_settings` key/value store.

Behavioural contract:
- GET   /admin/app-settings           — list every setting (key, value, description)
- GET   /admin/app-settings/{key}     — one setting
- PUT   /admin/app-settings/{key}     — change `value` (description is immutable)

There is no POST/DELETE — settings are seeded by migrations. The admin
UI just lets you tune the values that ops needs to adjust without a
backend redeploy (SMS cap, IP block thresholds, future feature flags).

Writes (PUT) are admin-only; GET also allows `marketing` (read-only) since
the Рефералы page reads through here. Updates bust the Redis cache so other
replicas see the new value within milliseconds.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import allow_settings_read_or_admin_write, get_app_settings_service
from app_config.dtos import AppSettingDTO, AppSettingUpdateDTO
from app_config.service import AppSettingsService

router = APIRouter(
    prefix="/admin/app-settings",
    tags=["admin"],
    dependencies=[Depends(allow_settings_read_or_admin_write)],
)


@router.get(
    "",
    response_model=list[AppSettingDTO],
    summary="Все runtime-настройки",
)
def list_settings(
    service: AppSettingsService = Depends(get_app_settings_service),
):
    return service.list_all()


@router.get(
    "/{key}",
    response_model=AppSettingDTO,
    summary="Получить одну настройку",
)
def get_setting(
    key: str,
    service: AppSettingsService = Depends(get_app_settings_service),
):
    setting = service.get_one(key)
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return setting


@router.put(
    "/{key}",
    response_model=AppSettingDTO,
    summary="Изменить значение настройки",
)
def update_setting(
    key: str,
    body: AppSettingUpdateDTO,
    service: AppSettingsService = Depends(get_app_settings_service),
):
    setting = service.update_value(key, body.value)
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return setting
