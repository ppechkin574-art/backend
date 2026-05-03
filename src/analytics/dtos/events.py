from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventCreateServiceDTO(BaseModel):
    user_id: UUID | None = None
    device_id: str
    session_id: str
    event_name: str
    event_time: datetime
    platform: str | None = None
    app_version: str | None = None
    os_version: str | None = None
    country: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    meta: dict[str, Any] | None = None


class EventCreateRepositoryDTO(EventCreateServiceDTO):
    model_config = ConfigDict(from_attributes=True)
