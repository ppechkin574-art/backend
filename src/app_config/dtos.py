from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AppSettingDTO(BaseModel):
    """Full row, returned from admin GET endpoints."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    description: str
    updated_at: datetime


class AppSettingUpdateDTO(BaseModel):
    """Only `value` is mutable. `description` is set in the migration that
    introduces the setting and stays stable so the meaning of the key
    doesn't shift unannounced. Add a new key + migrate the old one if
    semantics need to change."""

    value: str = Field(min_length=1, max_length=4096)
