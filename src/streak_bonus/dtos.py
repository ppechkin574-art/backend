"""Wire shapes for the streak-bonus feature.

Public reads (used by iOS home screen):
- `DailyStreakStatusDTO` — drives the modal: should it open today,
  what reward is sitting on the table, what's the current balance.

Public writes:
- `ClaimResultDTO` — after the user taps «Вернуться к предметам»
  the client gets the new balance back so it can update the header
  pill without a separate Bank fetch.

Admin CRUD shapes — `LeaderboardPrize`-style key/value tables, no
description column (the threshold is the row identity).
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class StreakRewardTierDTO(BaseModel):
    min_streak: int
    coins: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StreakRewardTierCreateDTO(BaseModel):
    min_streak: int = Field(..., ge=1, le=365)
    coins: int = Field(..., ge=0, le=100_000)
    is_active: bool = True


class StreakRewardTierUpdateDTO(BaseModel):
    coins: int | None = Field(default=None, ge=0, le=100_000)
    is_active: bool | None = None


class DailyStreakStatusDTO(BaseModel):
    """Snapshot the iOS home screen reads on launch to decide
    whether to pop the streak modal."""

    current_streak: int = Field(..., description="Активный стрик пользователя")
    claim_date: date | None = Field(
        None,
        description="Дата, за которую посчитана награда (если применима). null если стрик = 0.",
    )
    has_claimed_today: bool = Field(
        ...,
        description="True, если бонус сегодня уже забран — UI скрывает модалку.",
    )
    reward_coins: int = Field(
        ...,
        description="Сколько монет получит пользователь при тапе «Забрать» (или уже получил).",
    )
    balance: int = Field(..., description="Текущий баланс монет в кошельке.")


class ClaimResultDTO(BaseModel):
    coins_credited: int
    new_balance: int
    streak_after_claim: int
