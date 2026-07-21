"""Admin-editable copy for the «Скоро запускаем» screen — the single
`coming_soon_settings` row, plus read-side defaults so the screen has text
even before a row exists. Mirrors battle/settings.py."""
from pydantic import BaseModel, Field

from coming_soon.models import ComingSoonSettings

# Code defaults — the current l10n strings. Used when there is no row yet
# (and seeded into the first row created by get_or_create).
DEFAULTS = {
    "title1_ru": "Скоро ",
    "title1_kk": "Жақында ",
    "title2_ru": "запускаем!",
    "title2_kk": "іске қосамыз!",
    "subtitle_ru": "«{title}» откроется совсем скоро.\nМы сообщим тебе первому.",
    "subtitle_kk": "«{title}» жақын арада ашылады.\nБіз сізге бірінші хабарлаймыз.",
}

_WRITABLE = frozenset(DEFAULTS.keys())


def get_or_create_coming_soon_settings(session) -> ComingSoonSettings:
    row = session.query(ComingSoonSettings).first()
    if row is None:
        row = ComingSoonSettings(**DEFAULTS)
        session.add(row)
        session.flush()
    return row


def save_coming_soon_settings(session, changes: dict) -> ComingSoonSettings:
    row = get_or_create_coming_soon_settings(session)
    for k, v in changes.items():
        if k in _WRITABLE and v is not None:
            setattr(row, k, v)
    session.flush()
    return row


class ComingSoonSettingsDTO(BaseModel):
    title1_ru: str
    title1_kk: str
    title2_ru: str
    title2_kk: str
    subtitle_ru: str
    subtitle_kk: str

    model_config = {"from_attributes": True}


class ComingSoonSettingsUpdateDTO(BaseModel):
    """Partial update — only the fields present are applied."""

    title1_ru: str | None = Field(default=None, max_length=200)
    title1_kk: str | None = Field(default=None, max_length=200)
    title2_ru: str | None = Field(default=None, max_length=200)
    title2_kk: str | None = Field(default=None, max_length=200)
    subtitle_ru: str | None = Field(default=None, max_length=1000)
    subtitle_kk: str | None = Field(default=None, max_length=1000)
