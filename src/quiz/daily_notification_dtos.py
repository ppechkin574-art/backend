from datetime import datetime

from pydantic import BaseModel, Field


class DailyNotificationTemplateDTO(BaseModel):
    enabled: bool
    title: str
    body: str
    hour: int
    minute: int
    timezone: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyNotificationTemplateUpdateDTO(BaseModel):
    enabled: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=500)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class DailyNotificationTriggerResultDTO(BaseModel):
    requested: int
    delivered: int
    failed: int
    skipped_disabled: bool
