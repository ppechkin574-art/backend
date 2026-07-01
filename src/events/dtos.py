from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EventDTO(BaseModel):
    id: int
    type: str
    badge_text: str
    title: str
    prize_text: str | None
    subtitle: str | None
    secondary_text: str | None
    deadline: datetime | None
    button_text: str | None
    bg_color: str | None
    progress_current: int | None
    progress_max: int | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


_VALID_TYPES = ("banner", "card")


class EventCreateDTO(BaseModel):
    type: str
    badge_text: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=300)
    prize_text: str | None = Field(default=None, max_length=100)
    subtitle: str | None = Field(default=None, max_length=2000)
    secondary_text: str | None = Field(default=None, max_length=300)
    deadline: datetime | None = None
    button_text: str | None = Field(default=None, max_length=100)
    bg_color: str | None = Field(default=None, max_length=20)
    progress_current: int | None = None
    progress_max: int | None = None
    sort_order: int = 0
    is_active: bool = True

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"type must be one of {list(_VALID_TYPES)}")
        return v


class EventUpdateDTO(BaseModel):
    """Все поля опциональны — PATCH обновляет только переданные."""

    type: str | None = None
    badge_text: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    prize_text: str | None = None
    subtitle: str | None = None
    secondary_text: str | None = None
    deadline: datetime | None = None
    button_text: str | None = None
    bg_color: str | None = None
    progress_current: int | None = None
    progress_max: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_TYPES:
            raise ValueError(f"type must be one of {list(_VALID_TYPES)}")
        return v
