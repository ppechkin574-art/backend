from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from common.enums import PlanType


class PromocodeCreateDTO(BaseModel):
    """DTO для создания промокода"""

    code: str
    plan_type: PlanType
    duration_days: int
    max_activations: int = 100
    description: str | None = None
    expires_at: datetime | None = None
    created_by: str = "admin"
    is_trial: bool = False
    is_reusable: bool = False

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if len(v) < 4:
            raise ValueError("Код промокода должен содержать минимум 4 символа")
        return v.upper()

    @field_validator("duration_days")
    @classmethod
    def validate_duration_days(cls, v):
        if v <= 0:
            raise ValueError("Длительность должна быть положительной")
        return v

    @field_validator("max_activations")
    @classmethod
    def validate_max_activations(cls, v):
        if v <= 0:
            raise ValueError("Максимальное количество активаций должно быть положительным")
        return v


class PromocodeDTO(BaseModel):
    """DTO промокода"""

    id: int
    code: str
    description: str | None
    plan_type: str
    duration_days: int
    max_activations: int
    activations_count: int
    expires_at: str | None
    created_by: UUID
    created_at: str
    is_trial: bool = False
    is_reusable: bool = False

    @field_validator("created_by", mode="before")
    @classmethod
    def _ensure_created_by_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    @field_validator("is_trial", "is_reusable", mode="before")
    @classmethod
    def _bool_defaults(cls, v):
        return False if v is None else v

    class Config:
        from_attributes = True


class PromocodeUsageStatsDTO(BaseModel):
    """DTO статистики использования промокода"""

    id: int
    user_id: str
    activated_at: str
    expires_at: str
    plan: str


class PromocodeStatsDTO(PromocodeDTO):
    """DTO статистики промокода с информацией об использованиях"""

    usage_stats: dict[str, Any]
    usages: list[PromocodeUsageStatsDTO]


class PromocodeActivationResultDTO(BaseModel):
    """DTO результата активации промокода"""

    success: bool
    message: str
    plan: str
    duration_days: int
    expires_at: str | None
    is_trial: bool
    promocode_id: int | None = None
    usage_id: int | None = None


class PromocodeUsageDTO(BaseModel):
    """DTO использования промокода"""

    id: int
    promocode_id: int
    promocode_code: str
    user_id: str
    activated_at: str
    expires_at: str
    activated_plan: str
    is_active: bool = False

    @field_validator("is_active", mode="before")
    @classmethod
    def set_is_active(cls, _v, info):
        expires_at = info.data.get("expires_at")
        if expires_at:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return expires_at > datetime.now(UTC)
        return False


class UserPromocodeHistoryDTO(BaseModel):
    """DTO истории промокодов пользователя"""

    user_id: str
    total_promocodes_used: int
    active_promocodes: list[PromocodeUsageDTO]
    expired_promocodes: list[PromocodeUsageDTO]


class PromocodeListResponseDTO(BaseModel):
    """DTO списка промокодов"""

    total: int
    page: int
    page_size: int
    items: list[PromocodeDTO]


class PromocodeUsageListResponseDTO(BaseModel):
    """DTO списка использований промокодов"""

    total: int
    page: int
    page_size: int
    items: list[PromocodeUsageDTO]


class CreatePromocodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=64, description="Код промокода")
    plan_type: PlanType = Field(PlanType.FREE, description="Тип плана подписки")
    duration_days: int = Field(..., gt=0, description="Длительность в днях")
    max_activations: int = Field(100, gt=0, description="Максимальное количество активаций")
    description: str | None = Field(None, max_length=255, description="Описание промокода")
    expires_at: datetime | None = Field(None, description="Дата истечения промокода")
    is_trial: bool = Field(False, description="Пробный период")
    is_reusable: bool = Field(False, description="Может ли использоваться многократно одним пользователем")


class UpdatePromocodeRequest(BaseModel):
    description: str | None = Field(None, max_length=255)
    max_activations: int | None = Field(None, gt=0)
    expires_at: datetime | None = None
    is_trial: bool | None = None
    is_reusable: bool | None = None


class BulkCreateRequest(BaseModel):
    count: int = Field(1, ge=1, le=100, description="Количество промокодов для создания")
    prefix: str = Field("PROMO", description="Префикс для кодов")
    plan_type: PlanType = Field(..., description="Тип плана")
    duration_days: int = Field(..., gt=0)
    max_activations: int = Field(1, gt=0)
    description: str | None = None
    expires_at: datetime | None = None
    is_trial: bool = False
