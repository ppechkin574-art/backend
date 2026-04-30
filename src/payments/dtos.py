from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from common.enums import PlanType


class PaymentStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELED = "canceled"


class CreatePaymentResponse(BaseModel):
    redirect_url: str = Field(..., description="Ссылка на платёжную страницу FP")
    order_id: str = Field(..., description="Уникальный идентификатор заказа/платежа")
    websocket_url: str = Field(..., description="Ссылка для подписки на изменения заказа/платежа")
    ws_token: str = Field(..., description="Одноразовый токен для авторизации WebSocket соединения")


class PaymentStatusUpdate(BaseModel):
    type: str = "payment_status_updated"
    order_id: str
    new_status: str
    old_status: str
    timestamp: datetime | None = None


class OrderSummaryDTO(BaseModel):
    order_id: str
    status: str
    amount: Decimal
    currency: str
    pg_payment_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderHistoryItem(BaseModel):
    status: str
    at: datetime

    model_config = {"from_attributes": True}


class OrderDetailDTO(BaseModel):
    order_id: str
    status: str
    amount: Decimal
    currency: str
    pg_payment_id: str | None = None
    pg_status_code: str | None = None
    pg_status_desc: str | None = None
    pg_card_pan: str | None = None
    pg_card_brand: str | None = None
    pg_card_exp: str | None = None
    pg_user_contact_email: str | None = None
    pg_user_phone: str | None = None
    created_at: datetime
    updated_at: datetime
    history: list[OrderHistoryItem] = []

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    results: int
    data: list[OrderSummaryDTO]


class GetUserOrders(BaseModel):
    user_id: str


class GetUserOrder(BaseModel):
    order_id: str


class GetUserOrderResponse(BaseModel):
    user_id: str


class CreatePaymentIn(BaseModel):
    amount: Decimal = Field(
        ...,
        example="1000.00",
        description="Сумма платежа (в валюте счета, например KZT).",
    )

    @field_validator("amount", mode="before")
    def parse_amount(cls, v):
        try:
            if isinstance(v, Decimal):
                return v
            return Decimal(str(v))
        except (InvalidOperation, ValueError):
            raise ValueError("amount must be a decimal number (e.g. 1000.00)")

    @field_validator("amount")
    def validate_amount(cls, v: Decimal):
        if v <= 1000:
            raise ValueError("amount must be > 1000")
        return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CreateSubscriptionPaymentIn(BaseModel):
    subscription_plan_id: int = Field(..., description="ID плана подписки из БД")
    months: int = Field(default=1, ge=1, le=12, description="Количество месяцев (от 1 до 12)")


class SubscriptionInfo(BaseModel):
    id: int
    user_id: str
    plan: PlanType
    status: str
    started_at: datetime | None = None
    expires_at: datetime | None = None
    days_remaining: int | None = None

    model_config = {"from_attributes": True}

    @field_validator("days_remaining", mode="before")
    def calculate_days_remaining(cls, _, info):
        if "expires_at" in info.data:
            expires_at = info.data["expires_at"]
            if expires_at:
                delta = expires_at - datetime.now(expires_at.tzinfo)
                return max(0, delta.days)
        return None


class PlanInfoDTO(BaseModel):
    id: int
    plan_type: PlanType
    name: str
    description: str
    duration_days: int
    price: Decimal = Field(..., description="Цена в KZT")
    original_price: Decimal | None = Field(None, description="Исходная цена (для отображения скидки)")
    discount_percent: int | None = Field(None, description="Процент скидки")
    features: dict[str, Any]
    is_recurring: bool
    trial_days: int
    is_active: bool
    is_visible: bool
    display_order: int

    model_config = {"from_attributes": True}

    @field_validator("discount_percent", mode="before")
    def calculate_discount(cls, v, info):
        if "price" in info.data and "original_price" in info.data:
            price = info.data["price"]
            original_price = info.data.get("original_price")

            if original_price and original_price > price and price > 0:
                return int((1 - price / original_price) * 100)
        return v


class AvailablePlansResponse(BaseModel):
    plans: list[PlanInfoDTO]


class SubscriptionStatusResponse(BaseModel):
    has_active_subscription: bool
    subscription: SubscriptionInfo | None = None
    features: dict[str, Any] | None = None
    has_promocode_access: bool = False
    promocode_expires_at: datetime | None = None


class CreatePlanRequest(BaseModel):
    plan_type: PlanType
    name: str
    description: str | None = None
    price: Decimal
    original_price: Decimal | None = None
    duration_days: int = Field(30, ge=1, description="Длительность в днях")
    is_recurring: bool = True
    trial_days: int = 0
    features: list[str] = Field(default_factory=list)
    limitations: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_visible: bool = True
    display_order: int = 0
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None


class UpdatePlanRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    original_price: Decimal | None = None
    duration_days: int | None = None
    is_recurring: bool | None = None
    trial_days: int | None = None
    features: list[str] | None = None
    limitations: dict[str, Any] | None = None
    is_active: bool | None = None
    is_visible: bool | None = None
    display_order: int | None = None
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None
