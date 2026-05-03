import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import get_promocode_service, get_user
from auth.dtos.users import UserDTO
from promocodes.dtos import (
    PromocodeActivationResultDTO,
    PromocodeDTO,
    PromocodeUsageDTO,
)
from promocodes.service import PromocodeService
from utils.monitoring import log_info

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/user/promocodes",
    tags=["User - Promocodes"],
)


class PromocodeActivateRequest(BaseModel):
    promocode: str = Field(..., description="Код промокода")


@router.post(
    "/activate",
    response_model=PromocodeActivationResultDTO,
    status_code=status.HTTP_200_OK,
    summary="Активировать промокод",
)
async def activate_promocode(
    request: PromocodeActivateRequest,
    user: UserDTO = Depends(get_user),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """
    Активировать промокод для получения подписки
    """
    try:
        # Safely get user_id for logging
        user_id_str = str(user.id) if user and hasattr(user, "id") and user.id else "unknown"

        log_info(
            "Promocode activation request",
            user_id=user_id_str,
            action="activate_promocode",
            promocode=request.promocode,
        )

        result = await promocode_service.get_promocode_activation_info(user, request.promocode)

        user_id_str = str(user.id) if user and hasattr(user, "id") and user.id else "unknown"
        log_info(
            "Promocode activation info retrieved",
            user_id=user_id_str,
            action="get_promocode_info",
            promocode=request.promocode,
            plan=result.plan,
            duration_days=result.duration_days,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error activating promocode: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/available",
    response_model=list[PromocodeDTO],
    summary="Доступные промокоды",
)
async def get_available_promocodes(
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """
    Получить список доступных промокодов
    """
    try:
        promocodes = await promocode_service.get_available_promocodes()
        return promocodes
    except Exception as e:
        logger.exception("Error getting available promocodes: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/history",
    response_model=list[PromocodeUsageDTO],
    summary="История активаций промокодов",
)
async def get_promocode_history(
    user: UserDTO = Depends(get_user),
    promocode_service: PromocodeService = Depends(get_promocode_service),
):
    """
    Получить историю активаций промокодов пользователем
    """
    try:
        history = await promocode_service.get_user_promocode_history(user.id)
        return history
    except Exception as e:
        logger.exception("Error getting promocode history: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
