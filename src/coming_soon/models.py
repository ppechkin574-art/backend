from sqlalchemy import Column, Integer, String, Text, func
from sqlalchemy import DateTime

from database import Base


class ComingSoonSettings(Base):
    """Single-row, admin-editable copy for the «Скоро запускаем» screen
    (shown when a not-yet-launched banner is tapped on Главная). Mirrors the
    battle_settings / leaderboard_points_settings pattern: text that used to be
    hardcoded l10n strings lives here so it can be changed from the admin panel
    without an app release. A missing row → code defaults (see settings.py).

    The two title parts render on one line, the second in the accent color.
    Subtitle is a template: the literal ``{title}`` is replaced by the tapped
    event's name in the app."""

    __tablename__ = "coming_soon_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title1_ru = Column(String(200), nullable=False, server_default="Скоро ")
    title1_kk = Column(String(200), nullable=False, server_default="Жақында ")
    title2_ru = Column(String(200), nullable=False, server_default="запускаем!")
    title2_kk = Column(String(200), nullable=False, server_default="іске қосамыз!")
    subtitle_ru = Column(Text, nullable=False)
    subtitle_kk = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
