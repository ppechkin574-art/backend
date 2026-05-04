from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from common.enums import PlanType
from utils.validators import KZPhone


class UserCreateDTO(BaseModel):
    name: str
    phone: KZPhone | None = None
    email: EmailStr | None = None
    avatar: str | None = None
    password: str | None = None
    role: str
    is_active: bool
    allowed_subject_ids: list[int] = Field(default_factory=list)
    plan: PlanType = PlanType.PRO
    subscription_end: datetime | None = None
    used_trial: bool = False


class UserQueryDTO(BaseModel):
    id: UUID | None = None
    phone: KZPhone | None = None
    email: EmailStr | None = None
    avatar: str | None = None


class UserDTO(BaseModel):
    id: UUID
    username: str
    name: str
    phone: KZPhone | None = None
    email: EmailStr | None = None
    avatar: str | None = None
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    # role: str = Field(default="user", exclude=False)
    allowed_subject_ids: list[int] = Field(default_factory=list)
    plan: PlanType = PlanType.FREE
    used_trial: bool = False
    subscription_end: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    attendance_streak_days: int = 0
    attendance_total_points: int = 0
    attendance_today_points: int | None = None

    points: int = 0
    rank: int | None = None

    @computed_field
    @property
    def role(self) -> str:
        if "parent" in self.roles:
            return "parent"
        elif "child" in self.roles:
            return "child"
        else:
            return "user"

    model_config = ConfigDict(
        exclude={"roles"},
        extra="ignore",
    )

    @property
    def has_active_subscription(self) -> bool:
        """Проверяет, есть ли активная подписка"""
        if self.plan == PlanType.FREE:
            return True

        if self.plan == PlanType.PRO:
            if self.subscription_end:
                return (
                    datetime.now(self.subscription_end.tzinfo) < self.subscription_end
                )
            return False

        return False


class UserUpdateDTO(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: KZPhone | None = None
    avatar: str | None = None
    plan: PlanType | None = None
    used_trial: bool | None = None
    subscription_end: datetime | None = None
    username: str | None = None


class UserTokensDTO(BaseModel):
    access_token: str
    refresh_token: str
