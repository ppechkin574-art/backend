"""Admin-editable battle tuning — the single `battle_settings` row, plus
read-side defaults so battle logic works even before a row exists. Mirrors the
sprint's leaderboard_points settings pattern."""
from pydantic import BaseModel, Field

from battle.models import BattleSettings

# Code defaults — used when there is no row yet (and as the seeded row values).
DEFAULTS = {
    "stars_win": 50,
    "stars_draw": 25,
    "stars_loss": 0,
    "questions_per_subject": 5,
    "time_seconds": 300,
    "bot_win_rate_min": 50,
    "bot_win_rate_max": 62,
}

_WRITABLE = frozenset(DEFAULTS.keys())


def get_or_create_battle_settings(session) -> BattleSettings:
    row = session.query(BattleSettings).first()
    if row is None:
        row = BattleSettings()
        session.add(row)
        session.flush()
    return row


def battle_setting(session, key: str) -> int:
    """One value, falling back to the code default — the read path for
    battle/service.py. isinstance(int) guards against a missing row / mock so
    the battle keeps working with defaults before any admin has configured it."""
    row = session.query(BattleSettings).first()
    val = getattr(row, key, None) if row is not None else None
    return val if isinstance(val, int) else DEFAULTS[key]


def save_battle_settings(session, changes: dict) -> BattleSettings:
    row = get_or_create_battle_settings(session)
    for k, v in changes.items():
        if k in _WRITABLE and v is not None:
            setattr(row, k, v)
    session.flush()
    return row


class BattleSettingsDTO(BaseModel):
    stars_win: int
    stars_draw: int
    stars_loss: int
    questions_per_subject: int
    time_seconds: int
    bot_win_rate_min: int
    bot_win_rate_max: int

    model_config = {"from_attributes": True}


class BattleSettingsUpdateDTO(BaseModel):
    """Partial update — only the fields present are applied."""

    stars_win: int | None = Field(default=None, ge=0, le=100_000)
    stars_draw: int | None = Field(default=None, ge=0, le=100_000)
    stars_loss: int | None = Field(default=None, ge=0, le=100_000)
    questions_per_subject: int | None = Field(default=None, ge=1, le=50)
    time_seconds: int | None = Field(default=None, ge=10, le=7200)
    bot_win_rate_min: int | None = Field(default=None, ge=0, le=100)
    bot_win_rate_max: int | None = Field(default=None, ge=0, le=100)
