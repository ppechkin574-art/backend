from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Locale = Literal["ru", "kz"]


class SubscriptionBenefitPublicDTO(BaseModel):
    """One bullet returned to the mobile client.

    The client never receives both locales — the backend resolves
    locale on the request side via ?lang=ru|kz so the network payload
    stays compact.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    title: str
    description: str


class SubscriptionBenefitAdminDTO(BaseModel):
    """Full row, returned from admin endpoints — both locales visible
    so the admin UI can present a side-by-side editor.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    title_ru: str
    title_kz: str
    description_ru: str
    description_kz: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionBenefitCreateDTO(BaseModel):
    position: int = Field(default=0, ge=0)
    title_ru: str = Field(min_length=1, max_length=200)
    title_kz: str = Field(min_length=1, max_length=200)
    description_ru: str = Field(min_length=1)
    description_kz: str = Field(min_length=1)
    is_active: bool = True


class SubscriptionBenefitUpdateDTO(BaseModel):
    """All fields optional so the admin UI can do partial PATCH-style
    updates without round-tripping the whole row.
    """

    position: int | None = Field(default=None, ge=0)
    title_ru: str | None = Field(default=None, min_length=1, max_length=200)
    title_kz: str | None = Field(default=None, min_length=1, max_length=200)
    description_ru: str | None = Field(default=None, min_length=1)
    description_kz: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
