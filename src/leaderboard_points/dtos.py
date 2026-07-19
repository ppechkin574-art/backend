from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# "interval"      — reset every `interval_days` days after the last reset.
# "weekly_monday" — reset every Monday 00:00 Asia/Almaty (CRM task #6,
#                    "Еженедельный спринт").
ResetMode = Literal["interval", "weekly_monday"]


class LeaderboardPointsSettingsDTO(BaseModel):
    auto_reset_enabled: bool
    reset_mode: ResetMode
    interval_days: int
    last_reset_at: datetime | None = None
    next_reset_at: datetime | None = None
    # CRM task #7 ("Еженедельный спринт"): points threshold that locks
    # in the week's sprint winner. None/0 == feature off.
    sprint_target_points: int | None = None
    updated_at: datetime
    updated_by: str | None = None

    model_config = {"from_attributes": True}


class LeaderboardPointsSettingsUpdateDTO(BaseModel):
    auto_reset_enabled: bool
    reset_mode: ResetMode = "interval"
    # Ignored when reset_mode == "weekly_monday", but still validated/stored
    # so switching back to "interval" restores the previous cadence.
    interval_days: int = Field(30, ge=1, le=3650)
    # None/0 disables the sprint-winner feature entirely (default).
    sprint_target_points: int | None = Field(default=None, ge=0, le=1_000_000)


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


class SprintWinnerDTO(BaseModel):
    """Public shape of the current week's locked-in sprint winner —
    used by GET /leaderboard/sprint. Name/avatar are resolved the same
    way as the rest of the leaderboard (user_display snapshot / Keycloak
    fallback), not re-derived here."""

    user_id: str
    name: str
    avatar_url: str | None = None
    points_at_win: int
    won_at: datetime
