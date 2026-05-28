"""Wire shapes for the leaderboard-prize feature.

`PRIZE_ICON_KEYS` is the canonical list of SVG assets the iOS client
ships under `assets/grand/icons/prizes/`. Admin UI populates the
icon-picker dropdown from this list. Backend validates incoming
values against it so the client never receives a key it can't
render.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Keep in sync with `assets/grand/icons/prizes/<key>.svg` in the
# Flutter project. Adding a new icon: drop the SVG, add the key here,
# push a backend migration is NOT needed (this is a Python constant
# tuple, not a DB column).
PRIZE_ICON_KEYS: tuple[str, ...] = (
    "trophy",
    "medal_gold",
    "medal_silver",
    "medal_bronze",
    "crown",
    "gift",
    "money",
    "diamond",
    "headphones",
    "certificate",
    "book",
)


class LeaderboardPrizeDTO(BaseModel):
    id: int
    rank: int
    icon_key: str
    title: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaderboardPrizeCreateDTO(BaseModel):
    rank: int = Field(..., ge=1, le=100)
    icon_key: str
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    is_active: bool = True

    @field_validator("icon_key")
    @classmethod
    def _validate_icon_key(cls, v: str) -> str:
        if v not in PRIZE_ICON_KEYS:
            raise ValueError(
                f"icon_key must be one of {list(PRIZE_ICON_KEYS)} (got {v!r})"
            )
        return v


class LeaderboardPrizeUpdateDTO(BaseModel):
    """All fields optional — admin can patch one column at a time."""

    rank: int | None = Field(default=None, ge=1, le=100)
    icon_key: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None

    @field_validator("icon_key")
    @classmethod
    def _validate_icon_key(cls, v: str | None) -> str | None:
        if v is not None and v not in PRIZE_ICON_KEYS:
            raise ValueError(
                f"icon_key must be one of {list(PRIZE_ICON_KEYS)} (got {v!r})"
            )
        return v


class IconKeyListDTO(BaseModel):
    """Returned by `GET /admin/leaderboard-prizes/icon-keys` so the
    admin web doesn't have to keep a hardcoded copy in sync."""

    icon_keys: list[str]
