import logging
import secrets
import string
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import (
    allow_read_or_admin_write,
    get_db_session,
    get_promocode_service,
)
from auth.dtos.users import UserDTO
from common.enums import PlanType
from promocodes.dtos import (
    BulkCreateRequest,
    CreatePromocodeRequest,
    PromocodeCreateDTO,
    PromocodeDTO,
    PromocodeListResponseDTO,
    PromocodeStatsDTO,
    PromocodeUsageDTO,
    PromocodeUsageListResponseDTO,
    UpdatePromocodeRequest,
)
from promocodes.service import PromocodeService
from utils.monitoring import log_info

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/promocodes",
    tags=["Admin - Promocodes"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.post(
    "",
    response_model=PromocodeDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Создать промокод",
)
async def create_promocode(
    request: CreatePromocodeRequest,
    user: UserDTO = Depends(allow_read_or_admin_write),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """Создать новый промокод"""
    try:
        create_dto = PromocodeCreateDTO(
            code=request.code.upper(),
            plan_type=request.plan_type,
            duration_days=request.duration_days,
            max_activations=request.max_activations,
            description=request.description,
            expires_at=request.expires_at,
            created_by=str(user.id),
            is_trial=request.is_trial,
            is_reusable=request.is_reusable,
        )

        promocode = await promocode_service.create_promocode(create_dto)

        log_info(
            "Promocode created by admin",
            action="admin_create_promocode",
            admin_id=user.id,
            promocode_code=request.code,
            plan_type=request.plan_type.value,
        )

        return promocode

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating promocode: %s{e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post(
    "/bulk",
    response_model=list[PromocodeDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Создать несколько промокодов",
)
async def bulk_create_promocodes(
    request: BulkCreateRequest,
    user: UserDTO = Depends(allow_read_or_admin_write),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """Создать несколько промокодов"""
    try:
        results = []

        for _i in range(request.count):
            suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits, k=8))
            code = f"{request.prefix}_{suffix}"

            create_dto = PromocodeCreateDTO(
                code=code,
                plan_type=request.plan_type,
                duration_days=request.duration_days,
                max_activations=request.max_activations,
                description=request.description,
                expires_at=request.expires_at,
                created_by=str(user.id),
                is_trial=request.is_trial,
                is_reusable=False,
            )

            try:
                promocode = await promocode_service.create_promocode(create_dto)
                results.append(promocode)
            except Exception as e:
                logger.warning("Failed to create promocode %s: %s", code, e)
                continue

        log_info(
            "Bulk promocodes created",
            action="admin_bulk_create_promocodes",
            admin_id=user.id,
            count_created=len(results),
            total_requested=request.count,
        )

        return results

    except Exception as e:
        logger.exception("Error in bulk create promocodes: %s{e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get(
    "",
    response_model=PromocodeListResponseDTO,
    summary="Список всех промокодов с пагинацией",
)
async def list_promocodes(
    _user: UserDTO = Depends(allow_read_or_admin_write),
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Размер страницы"),
    plan_type: PlanType | None = Query(None, description="Фильтр по типу плана"),
    active_only: bool = Query(False, description="Только активные промокоды"),
    db: Session = Depends(get_db_session),
):
    """Получить список всех промокодов с фильтрацией и пагинацией"""
    try:
        from promocodes.models import Promocode

        query = db.query(Promocode)

        if plan_type:
            query = query.filter(Promocode.plan_type == plan_type.value)

        if active_only:
            now = datetime.now(UTC)
            query = query.filter((Promocode.expires_at > now) | (Promocode.expires_at.is_(None)))

        total = query.count()
        offset = (page - 1) * page_size

        promocodes = query.order_by(Promocode.created_at.desc()).offset(offset).limit(page_size).all()

        items = []
        for p in promocodes:
            items.append(
                PromocodeDTO(
                    id=p.id,
                    code=p.code,
                    description=p.description,
                    plan_type=p.plan_type,
                    duration_days=p.duration_days,
                    max_activations=p.max_activations,
                    activations_count=p.activations_count,
                    expires_at=p.expires_at.isoformat() if p.expires_at else None,
                    created_by=p.created_by,
                    created_at=p.created_at.isoformat(),
                    is_trial=p.is_trial,
                    is_reusable=p.is_reusable,
                )
            )

        return PromocodeListResponseDTO(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )

    except Exception as e:
        logger.exception("Error listing promocodes: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{code}", response_model=PromocodeStatsDTO, summary="Статистика промокода")
async def get_promocode_stats(
    code: str,
    _user: UserDTO = Depends(allow_read_or_admin_write),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """Получить полную статистику использования промокода"""
    try:
        stats = await promocode_service.get_promocode_stats(code.upper())
        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting promocode stats: %s", e)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Промокод не найден")


@router.get(
    "/{code}/usages",
    response_model=PromocodeUsageListResponseDTO,
    summary="История использований промокода",
)
async def get_promocode_usages(
    code: str,
    _user: UserDTO = Depends(allow_read_or_admin_write),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Получить историю использований конкретного промокода"""
    try:
        from promocodes.models import Promocode, PromocodeUsage

        promocode = db.query(Promocode).filter(Promocode.code == code.upper()).first()

        if not promocode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Промокод не найден")

        query = db.query(PromocodeUsage).filter(PromocodeUsage.promocode_id == promocode.id)

        total = query.count()
        offset = (page - 1) * page_size

        usages = query.order_by(PromocodeUsage.activated_at.desc()).offset(offset).limit(page_size).all()

        items = []
        now = datetime.now(UTC)

        for usage in usages:
            items.append(
                PromocodeUsageDTO(
                    id=usage.id,
                    promocode_id=usage.promocode_id,
                    promocode_code=promocode.code,
                    user_id=usage.student_guid,
                    activated_at=usage.activated_at.isoformat(),
                    expires_at=usage.access_expires_at.isoformat(),
                    activated_plan=usage.activated_plan,
                    is_active=usage.access_expires_at > now,
                )
            )

        return PromocodeUsageListResponseDTO(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting promocode usages: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{code}", response_model=PromocodeDTO, summary="Обновить промокод")
async def update_promocode(
    code: str,
    update_data: UpdatePromocodeRequest,
    user: UserDTO = Depends(allow_read_or_admin_write),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """Обновить параметры промокода"""
    try:
        promocode = await promocode_service.validate_promocode(code.upper())

        update_dict = update_data.dict(exclude_unset=True)
        updated = await promocode_service.update_promocode(promocode.id, update_dict)

        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Промокод не найден")

        log_info(
            "Promocode updated by admin",
            action="admin_update_promocode",
            admin_id=user.id,
            promocode_code=code,
            updates=update_dict,
        )

        return updated

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating promocode: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="Деактивировать промокод")
async def deactivate_promocode(
    code: str,
    user: UserDTO = Depends(allow_read_or_admin_write),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """Деактивировать промокод (установить дату истечения в прошлое)"""
    try:
        success = await promocode_service.deactivate_promocode_by_code(code.upper())

        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Промокод не найден")

        log_info(
            "Promocode deactivated by admin",
            action="admin_deactivate_promocode",
            admin_id=user.id,
            promocode_code=code,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deactivating promocode: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/search/{search_term}",
    response_model=list[PromocodeDTO],
    summary="Поиск промокодов",
)
async def search_promocodes(
    search_term: str,
    _user: UserDTO = Depends(allow_read_or_admin_write),
    db: Session = Depends(get_db_session),
):
    """Поиск промокодов по коду или описанию"""
    try:
        from sqlalchemy import or_

        from promocodes.models import Promocode

        search_term = f"%{search_term}%"

        promocodes = (
            db.query(Promocode)
            .filter(
                or_(
                    Promocode.code.ilike(search_term),
                    Promocode.description.ilike(search_term),
                )
            )
            .order_by(Promocode.created_at.desc())
            .limit(50)
            .all()
        )

        return [
            PromocodeDTO(
                id=p.id,
                code=p.code,
                description=p.description,
                plan_type=p.plan_type,
                duration_days=p.duration_days,
                max_activations=p.max_activations,
                activations_count=p.activations_count,
                expires_at=p.expires_at.isoformat() if p.expires_at else None,
                created_by=p.created_by,
                created_at=p.created_at.isoformat(),
                is_trial=p.is_trial,
                is_reusable=p.is_reusable,
            )
            for p in promocodes
        ]

    except Exception as e:
        logger.exception("Error searching promocodes: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
