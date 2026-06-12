from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from common.enums import PlanType
from utils.validators import KZPhone


class KeycloakAttributesDTO(BaseModel):
    name: list[str]
    phone: list[KZPhone] | None = Field(default_factory=list)
    role: list[str] = Field(default=["user"])
    allowed_subject_ids: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=lambda: [PlanType.FREE.value])
    subscription_end: list[str] = Field(default_factory=list)
    subscription_cancelled: list[str] = Field(default_factory=list)
    used_trial: list[str] = Field(default_factory=list)
    grade: list[str] = Field(default_factory=list)
    avatar: list[str] | None = Field(default_factory=list)


class KeycloakCredentialDTO(BaseModel):
    type: str = Field(default="password")
    value: str
    temporary: bool = Field(default=False)


class KeycloakUserDTO(BaseModel):
    id: UUID
    username: str
    email: EmailStr | None = None
    emailVerified: bool = False
    attributes: KeycloakAttributesDTO | None = None
    createdTimestamp: datetime | None = None
    enabled: bool = True


class KeycloakCreateUserDTO(BaseModel):
    username: str
    email: EmailStr | None = None
    firstName: str | None = None
    lastName: str | None = None
    emailVerified: bool = Field(default=False)
    enabled: bool = Field(default=True)
    attributes: KeycloakAttributesDTO
    credentials: list[KeycloakCredentialDTO]


class KeycloakAccessTokenDTO(BaseModel):
    access_token: str
    expires_in: int
    refresh_expires_in: int
    refresh_token: str
    token_type: str
    id_token: str
    not_before_policy: int = Field(alias="not-before-policy")
    session_state: str
    scope: str


class KeycloakAttributesUpdateDTO(BaseModel):
    name: list[str] | None = None
    phone: list[str] | None = None
    avatar: list[str] | None = None
    allowed_subject_ids: list[str] | None = None
    plan: list[str] | None = None
    subscription_end: list[str] | None = None
    subscription_cancelled: list[str] | None = None
    used_trial: list[str] | None = None


class KeycloakUserUpdateDTO(BaseModel):
    email: EmailStr | None = None
    attributes: KeycloakAttributesUpdateDTO
    username: str | None = None


class KeycloakUserQueryDTO(BaseModel):
    id: UUID | None = None
    phone: KZPhone | None = None
    email: EmailStr | None = None
    username: str | None = None


class KeycloakUserSubscriptionUpdateDTO(BaseModel):
    """DTO для обновления подписки пользователя в Keycloak"""

    user_id: UUID
    plan: PlanType
    expires_at: datetime | None = None
