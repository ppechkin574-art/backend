from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PointsPolicyDTO(BaseModel):
    activity_type: str
    is_enabled: bool
    mode: Literal["fixed", "score_based"]
    fixed_points: int | None
    score_multiplier: float | None
    min_score_percent: int
    repeat_mode: Literal["always", "first_only", "improvement_only"]
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PointsPolicyUpdateDTO(BaseModel):
    is_enabled: bool | None = None
    mode: Literal["fixed", "score_based"] | None = None
    fixed_points: int | None = None
    score_multiplier: float | None = None
    min_score_percent: int | None = Field(None, ge=0, le=100)
    repeat_mode: Literal["always", "first_only", "improvement_only"] | None = None

    @model_validator(mode="after")
    def check_mode_fields(self) -> "PointsPolicyUpdateDTO":
        if self.mode == "fixed" and self.fixed_points is None and self.is_enabled:
            raise ValueError("fixed_points is required when mode='fixed' and is_enabled=true")
        if self.mode == "score_based" and self.score_multiplier is None and self.is_enabled:
            raise ValueError("score_multiplier is required when mode='score_based' and is_enabled=true")
        return self
