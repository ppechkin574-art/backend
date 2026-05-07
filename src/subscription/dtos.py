from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_validator

from common.enums import PlanType


class PlanFeaturesDTO(BaseModel):
    """DTO с фичами плана подписки"""

    id: int
    plan_type: PlanType
    name: str
    description: str
    price: float
    original_price: float | None = None
    duration_days: int
    is_recurring: bool = True
    trial_days: int = 0
    features: dict[str, Any]
    limitations: dict[str, Any]
    is_active: bool = True
    is_visible: bool = True
    display_order: int = 0


class SubscriptionPlanDTO(BaseModel):
    """DTO плана подписки для отображения в API"""

    type: str
    name: str
    description: str
    price: float
    original_price: float | None = None
    duration_days: int
    is_recurring: bool
    trial_days: int
    features: dict[str, bool]
    limitations: dict[str, Any]
    is_active: bool
    is_visible: bool
    display_order: int


class SubscriptionStatusDTO(BaseModel):
    """DTO статуса подписки пользователя"""

    plan: str
    plan_name: str
    plan_description: str
    is_active: bool
    expires_at: str | None
    features: dict[str, Any]
    limitations: dict[str, Any]
    price: float
    is_expired: bool = False
    days_left: int | None = None
    cancelled: bool = False

    @field_validator("is_expired", mode="before")
    @classmethod
    def _ensure_is_expired_bool(cls, v):
        return False if v is None else bool(v)

    def __init__(self, **data):
        super().__init__(**data)
        if data.get("expires_at"):
            expires = datetime.fromisoformat(data["expires_at"])
            self.days_left = max(0, (expires - datetime.now(UTC)).days)


class SubscriptionCreateDTO(BaseModel):
    """DTO для создания подписки"""

    user_id: str
    plan_type: PlanType
    months: int = 1
    payment_id: int | None = None
    promocode_id: int | None = None
    auto_renew: bool = True


class SubscriptionDTO(BaseModel):
    """DTO подписки"""

    id: int
    user_id: str
    plan_type: str
    status: str
    started_at: str | None
    expires_at: str | None
    cancelled_at: str | None
    auto_renew: bool
    payment_id: int | None = None
    promocode_usage_id: int | None = None
    notes: str | None = None
    created_at: str
    updated_at: str


class SubscriptionHistoryDTO(BaseModel):
    """DTO истории подписки"""

    id: int
    subscription_id: int
    old_status: str | None
    new_status: str
    event_type: str
    history_metadata: dict[str, Any] | None
    created_at: str
