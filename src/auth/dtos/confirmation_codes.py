from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConfirmationCodeAction(StrEnum):
    REGISTER = "register"
    RESET_PASSWORD = "reset_password"  # noqa S105
    CHANGE_EMAIL = "change_email"
    CHANGE_PHONE = "change_phone"


class ConfirmationCodeCreateDTO(BaseModel):
    user_id: UUID | None = None
    registration_id: UUID | None = None
    contact: str | None = None
    code: int
    expiration: int
    action: ConfirmationCodeAction
    is_temporary: bool = False


class ConfirmationCodeQueryDTO(BaseModel):
    user_id: UUID | None = None
    registration_id: UUID | None = None
    contact: str | None = None
    code: int | None = None
    action: ConfirmationCodeAction | None = None
    is_temporary: bool = False


class ConfirmationCodeDTO(BaseModel):
    id: UUID
    user_id: UUID | None = None
    registration_id: UUID | None = None
    contact: str | None = None
    code: int
    correct: bool
    action: ConfirmationCodeAction
    incorrect_count: int
    created_at: datetime | None = None
    expires_at: datetime | None = None


class RedisConfirmationCodeDTO(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    contact: str | None = None
    code: int
    action: ConfirmationCodeAction
    incorrect_count: int = Field(default=0)
    is_temporary: bool = Field(default=False)
    created_at: str
    expires_at: float
    real_user_id: str | None = None
