"""Lightweight Telegram notifier for new-user registration events.

Separate from the OTP Telegram bot (telegram_otp) — this one posts to
an admin monitoring channel so the team sees every new sign-up in real time.

Configuration (Railway env vars):
    TELEGRAM_REG__TOKEN   — bot token from @BotFather
    TELEGRAM_REG__CHAT_ID — channel/group chat_id (negative for channels)

If either var is absent the notifier silently skips — zero-risk for the
registration flow itself.
"""

from __future__ import annotations

import logging

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class TelegramRegSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_REG__", extra="ignore")

    token: str = ""
    chat_id: str = ""


class TelegramRegistrationNotifier:
    """Fire-and-forget Telegram message on new user registration."""

    def __init__(self, settings: TelegramRegSettings | None = None) -> None:
        self._settings = settings or TelegramRegSettings()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.token and self._settings.chat_id)

    def notify_new_user(
        self,
        name: str,
        phone: str | None,
        platform: str | None = None,
    ) -> None:
        if not self.enabled:
            return

        platform_emoji = {"ios": "🍎", "android": "🤖"}.get((platform or "").lower(), "📱")
        phone_display = phone or "—"
        text = (
            f"🆕 <b>Новый пользователь</b>\n"
            f"👤 {name}\n"
            f"📞 {phone_display}\n"
            f"{platform_emoji} {platform or 'неизвестно'}"
        )

        url = f"https://api.telegram.org/bot{self._settings.token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self._settings.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning("Telegram reg notify failed: %s", resp.text)
        except Exception:
            logger.debug("Telegram reg notify error (non-fatal)", exc_info=True)
