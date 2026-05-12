import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_payment_service,
    get_subscription_service,
    get_user,
    get_ws_token_manager,
)
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.dtos import (
    CreatePaymentResponse,
    CreateSubscriptionPaymentIn,
    SubscriptionInfo,
)
from payments.dtos import (
    SubscriptionStatusResponse as PaymentSubscriptionStatusResponse,
)
from payments.services import PaymentService
from payments.ws_tokens import WebSocketTokenManager
from promocodes.models import PromocodeUsage
from subscription.models import Subscription, SubscriptionStatus
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/user/subscription",
    tags=["User - Subscription"],
    dependencies=[Depends(get_user)],
)


class SubscriptionStatusResponse(BaseModel):
    plan: str
    plan_name: str
    is_active: bool
    expires_at: str | None
    features: dict[str, Any]
    is_expired: bool
    cancelled: bool = False


class SubscriptionPlanResponse(BaseModel):
    id: int = Field(..., description="ID плана в БД")
    type: str = Field(..., description="Тип плана")
    name: str = Field(..., description="Название плана")
    description: str = Field(..., description="Описание плана")
    price: float = Field(..., description="Цена")
    features: dict[str, Any] = Field(..., description="Доступные фичи")
    limitations: dict[str, Any] | None = Field(None, description="Ограничения плана")
    duration_days: int | None = Field(None, description="Длительность плана в днях")
    original_price: float | None = Field(None, description="Оригинальная цена")
    discount_percent: int | None = Field(None, description="Процент скидки")
    is_recurring: bool | None = Field(None, description="Автопродление")
    trial_days: int | None = Field(None, description="Пробный период в днях")
    display_order: int | None = Field(None, description="Порядок отображения")
    benefit_items: list[dict[str, Any]] = Field(default_factory=list, description="Список преимуществ подписки")


class ActivateSubscriptionRequest(BaseModel):
    plan: str
    months: int = 1


@router.get(
    "/status",
    response_model=SubscriptionStatusResponse,
    summary="Статус подписки (из Keycloak)",
)
async def get_subscription_status(
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Получить текущий статус подписки из Keycloak"""
    try:
        status_data = await subscription_service.check_subscription_status(user)
        return SubscriptionStatusResponse(**status_data)
    except Exception as e:
        logger.exception("Error getting subscription status: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/plans",
    response_model=list[SubscriptionPlanResponse],
    summary="Доступные планы подписки",
)
async def get_subscription_plans(
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Получить список доступных планов подписки"""
    try:
        plans = await subscription_service.get_subscription_plans()
        return plans
    except Exception as e:
        logger.exception("Error getting subscription plans: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/detailed-status",
    response_model=PaymentSubscriptionStatusResponse,
    summary="Детальный статус подписки (с промокодами)",
)
async def get_detailed_subscription_status(
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Получение детального статуса подписки пользователя (с промокодами)"""
    try:
        updated_user = subscription_service.refresh_subscription_status(user)

        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.user_id == str(user.id),
                Subscription.status == SubscriptionStatus.ACTIVE.value,
                Subscription.expires_at > datetime.now(UTC),
            )
            .first()
        )

        promocode_access = None
        try:
            promocode_access = (
                db.query(PromocodeUsage)
                .filter(
                    PromocodeUsage.student_guid == user.id,
                    PromocodeUsage.access_expires_at > datetime.now(UTC),
                )
                .first()
            )
        except Exception as e:
            logger.debug("PromocodeUsage query failed: %s", str(e))

        has_active_subscription = updated_user.has_active_subscription or (subscription is not None)

        subscription_info = None
        features = None

        if has_active_subscription:
            features = subscription_service.get_available_features(updated_user)

            if subscription:
                subscription_info = SubscriptionInfo.model_validate(subscription)

        return PaymentSubscriptionStatusResponse(
            has_active_subscription=has_active_subscription,
            subscription=subscription_info,
            features=features,
            has_promocode_access=promocode_access is not None,
            promocode_expires_at=(promocode_access.access_expires_at if promocode_access else None),
        )
    except Exception as e:
        logger.exception("Error getting detailed subscription status: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/create-payment",
    response_model=CreatePaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать платеж за подписку",
)
async def create_subscription_payment(
    subscription_data: CreateSubscriptionPaymentIn,
    user: UserDTO = Depends(get_user),
    payment_service: PaymentService = Depends(get_payment_service),
    ws_token_manager: WebSocketTokenManager = Depends(get_ws_token_manager),
    request: Request = None,
):
    """Создание платежа для подписки"""
    try:
        client_ip = request.client.host if request.client else None
        payment = await payment_service.create_subscription_payment(
            subscription_plan_id=subscription_data.subscription_plan_id,
            months=subscription_data.months,
            user_ip=client_ip,
        )

        ws_token = ws_token_manager.create_ws_token(
            user_id=str(user.id),
            order_id=payment.order_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        host = request.headers.get("host", "")
        if not host:
            base_url_str = str(request.base_url)
            if base_url_str.startswith("http://"):
                host = base_url_str[7:]
            elif base_url_str.startswith("https://"):
                host = base_url_str[8:]
            else:
                host = base_url_str

        if host.endswith(":80"):
            host = host[:-3]
        elif host.endswith(":443"):
            host = host[:-4]

        scheme = request.url.scheme
        ws_protocol = "wss" if scheme == "https" else "ws"

        websocket_url = f"{ws_protocol}://{host}/payments/ws/{payment.order_id}"

        return CreatePaymentResponse(
            redirect_url=payment.pg_redirect_url,
            order_id=payment.order_id,
            websocket_url=websocket_url,
            ws_token=ws_token,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating subscription payment: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history", response_model=list[SubscriptionInfo], summary="История подписок")
async def get_subscription_history(
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
):
    """Получение истории подписок пользователя"""
    try:
        subscriptions = (
            db.query(Subscription)
            .filter(Subscription.user_id == str(user.id))
            .order_by(Subscription.created_at.desc())
            .all()
        )

        return [SubscriptionInfo.model_validate(sub) for sub in subscriptions]
    except Exception as e:
        logger.exception("Error getting subscription history: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/free-trial",
    response_model=SubscriptionStatusResponse,
    summary="Активировать бесплатный пробный период",
    deprecated=True,
)
async def activate_free_trial(
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Активировать бесплатный пробный период на 7 дней"""
    updated_user = await subscription_service.activate_free_trial(user)
    status_data = await subscription_service.check_subscription_status(updated_user)
    return SubscriptionStatusResponse(**status_data)


@router.post(
    "/cancel",
    response_model=SubscriptionStatusResponse,
    summary="Отменить подписку (soft cancel)",
)
async def cancel_subscription(
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Soft-отмена подписки.

    Подписка остаётся активной до `subscription_end`, после чего юзер
    автоматически становится FREE (см. refresh_subscription_status).
    Флаг `subscription_cancelled=True` сохраняется в Keycloak attributes
    и не сбрасывается автоматически при последующих покупках (требуется
    явное возобновление через UI настроек).
    """
    updated_user = await subscription_service.cancel_subscription(user)
    status_data = await subscription_service.check_subscription_status(updated_user)
    return SubscriptionStatusResponse(**status_data)


@router.post(
    "/activate",
    response_model=SubscriptionStatusResponse,
    summary="Активировать подписку (без оплаты, для тестов)",
    deprecated=True,
)
async def activate_subscription(
    request: ActivateSubscriptionRequest,
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Активировать платную подписку (для тестов)"""
    try:
        plan = PlanType(request.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan type")

    updated_user = await subscription_service.activate_subscription(user, plan, request.months)
    status_data = await subscription_service.check_subscription_status(updated_user)
    return SubscriptionStatusResponse(**status_data)


@router.post("/cancel", summary="Отменить подписку (soft-cancel)")
async def cancel_subscription(
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Soft-cancel: подписка остаётся активной до конца оплаченного периода,
    но не продлевается. Флаг subscription_cancelled=true сохраняется в Keycloak."""
    await subscription_service.cancel_subscription(user)
    return {"detail": "Subscription cancelled successfully"}


@router.get("/features", summary="Доступные фичи текущего плана")
async def get_available_features(
    user: UserDTO = Depends(get_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
):
    """Получить список доступных фич для текущего плана"""
    return subscription_service.get_available_features(user)
