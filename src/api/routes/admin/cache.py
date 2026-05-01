from fastapi import APIRouter, Depends
from dependency_injector.wiring import Provide, inject

from api.containers import Container
from api.dependencies import allow_only_admins
from utils.cache import CacheService

router = APIRouter(
    prefix="/admin/cache",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.post(
    "/flush",
    summary="Сбросить весь кеш",
    description=(
        "Полностью очищает Redis-кеш приложения. Использовать после массового изменения "
        "контента в БД (например, импорт вопросов, накат дампа), чтобы исключить "
        "выдачу устаревших данных."
    ),
)
@inject
def flush_cache(
    cache_service: CacheService = Depends(Provide[Container.cache_service]),
):
    success = cache_service.flush_all()
    return {"flushed": success}


@router.post(
    "/invalidate",
    summary="Инвалидировать кеш по списку ресурсов",
    description=(
        "Удаляет ключи кеша для перечисленных ресурсов (например `subjects`, `topics`, "
        "`questions`). Точечный аналог /flush."
    ),
)
@inject
def invalidate_resources(
    resources: list[str],
    cache_service: CacheService = Depends(Provide[Container.cache_service]),
):
    deleted = cache_service.invalidate_by_resources(resources)
    return {"deleted_keys": deleted}
