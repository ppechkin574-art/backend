from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LeaderboardPointsSettingsDTO(BaseModel):
    auto_reset_enabled: bool
    interval_days: int
    last_reset_at: datetime | None = None
    next_reset_at: datetime | None = None
    updated_at: datetime
    updated_by: str | None = None

    model_config = {"from_attributes": True}


class LeaderboardPointsSettingsUpdateDTO(BaseModel):
    auto_reset_enabled: bool
    interval_days: int = Field(..., ge=1, le=3650)


class PointsAdjustDTO(BaseModel):
    delta: int
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("delta")
    @classmethod
    def _validate_delta(cls, v: int) -> int:
        if v == 0:
            raise ValueError("delta must not be 0")
        return v


class PointsAdjustResultDTO(BaseModel):
    user_id: str
    points_before: int
    points_after: int
    points_delta: int


class PointsResetResultDTO(BaseModel):
    ran: bool
    users_reset: int = 0
    next_reset_at: datetime | None = None
