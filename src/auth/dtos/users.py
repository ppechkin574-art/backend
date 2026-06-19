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
    plan: PlanType = PlanType.FREE
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
    # Школьный класс (5..11). None для:
    #   * родителей (роль parent — у них своего класса нет),
    #   * учителей и админов,
    #   * legacy-юзеров зарегистрированных до 09.05.2026 (поле введено
    #     задним числом, для них Keycloak-атрибут пустой).
    grade: int | None = None
    plan: PlanType = PlanType.FREE
    used_trial: bool = False
    subscription_end: datetime | None = None
    # True if the user has tapped "Cancel subscription" — current period
    # remains active until subscription_end, then auto-downgrades to FREE.
    # Persists across new purchases (Q8-B): user must explicitly resume
    # auto-renewal in settings (UI not yet implemented).
    subscription_cancelled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    attendance_streak_days: int = 0
    attendance_total_points: int = 0
    attendance_today_points: int | None = None

    # Leaderboard "stars" — the value the in-app leaderboard ranks by.
    # Sourced from `user_points.total_points` (same as the mobile get_user
    # flow in dependencies.py). NOTE: the admin list previously populated
    # this from `students.rating`, a separate legacy trainer rating, which
    # diverged from what the user actually sees. It now matches the app.
    # This is also the field the admin "edit points" action mutates.
    points: int = 0
    rank: int | None = None

    # Best-effort device / version / activity signals, enriched from the
    # latest analytics event (`user_activity`) with a device-token platform
    # fallback. May be None for users who have never sent an analytics event
    # or registered a push token — coverage is PARTIAL (FCM is disabled), so
    # the admin UI must tolerate missing values.
    device_platform: str | None = None       # "ios" / "android"
    device_os_version: str | None = None      # e.g. "17.4" / "14"
    app_version: str | None = None            # last-known build the app reported
    last_active_at: datetime | None = None    # latest analytics event_time

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
    subscription_cancelled: bool | None = None
    username: str | None = None


class UserTokensDTO(BaseModel):
    access_token: str
    refresh_token: str
