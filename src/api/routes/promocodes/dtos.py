from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PromocodeActivateRequestDTO(BaseModel):
    promocode: str


class PromocodeAccessDTO(BaseModel):
    access_days: int
    access_expires_at: datetime


class PromocodeActivateResponseDTO(BaseModel):
    status: str
    message: str
    access: PromocodeAccessDTO


class PromocodeCreateRequestDTO(BaseModel):
    duration_days: Literal[7, 14, 30] = Field(..., description="Количество дней доступа")
    max_activations: int = Field(..., gt=0, description="Сколько пользователей могут активировать промокод")
    code: str | None = Field(None, description="Необязательный код (если не задан, генерируется автоматически)")
    expires_at: datetime | None = Field(None, description="Дата, когда промокод перестает быть доступным для активации")
    description: str | None = None


class PromocodeResponseDTO(BaseModel):
    id: int
    code: str
    description: str | None = None
    duration_days: int
    max_activations: int
    activations_count: int
    expires_at: datetime | None = None
    created_at: datetime


class PromocodeHistoryItemDTO(BaseModel):
    id: int
    student_guid: UUID
    activated_at: datetime
    access_expires_at: datetime
