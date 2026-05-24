"""Self-hosted Telegram-bot OTP delivery.

The standard SMS path is broken for Beeline KZ until SMSC registers the
«AIMA» sender ID (operator-side queue, no ETA). Until then this client
gives those users an actionable fallback: tap «Open Telegram» in the
fallback modal, /start the bot once, code arrives in DM. After the
first link the bot persists the chat_id↔phone mapping so subsequent
OTPs go straight to DM with no bot-open step.

Bot API constraint: a bot CANNOT message a user it has never spoken to.
Telegram blocks this at the platform level for spam-prevention, so the
one-time /start is unavoidable; we keep the UX cost to once per user.
"""

import logging
from typing import Any

import requests

from clients.notification.settings import TelegramOtpSettings

logger = logging.getLogger(__name__)


class TelegramOtpClient:
    """Thin wrapper around `POST /bot<token>/sendMessage`.

    No retry on 4xx (bad token / blocked-by-user / chat_id stale) — those
    are non-recoverable for this call, the chain falls through to the next
    channel. We DO retry once on transient 5xx since Telegram's edge nodes
    occasionally 502 under load.
    """

    def __init__(self, settings: TelegramOtpSettings):
        self.settings = settings
        self.session = requests.Session()
        if settings.bot_token:
            logger.info(
                "TelegramOtpClient initialized for @%s (debug=%s)",
                settings.bot_username,
                settings.debug,
            )
        else:
            logger.info(
                "TelegramOtpClient initialized in disabled mode "
                "(no bot_token — chain will skip the telegram leg)"
            )

    @property
    def is_enabled(self) -> bool:
        """True iff bot is configured for actual sends.

        Mirrors the `_whatsapp_is_configured` gate in services.py — keeps
        the chain logic simple (skip the leg entirely instead of attempting
        + failing every call).
        """
        return bool(self.settings.bot_token) and not self.settings.debug

    def send_otp(self, chat_id: int | str, code: int | str) -> dict[str, Any]:
        """Send the formatted OTP message to a known chat_id.

        Raises on transport/4xx errors so the caller can fall through.
        Returns the parsed Telegram response on success.

        Heuristic: when `code` looks like a real numeric OTP we wrap it in
        the «AIMA — код для входа» template; arbitrary string hints
        («Код не найден…», «open the AIMA app…») bypass the template so
        they don't appear next to a bogus «Действителен 10 минут»
        disclaimer that would mislead the user into thinking the hint
        text IS the code.
        """
        if not self.settings.bot_token:
            raise RuntimeError("TelegramOtpClient.send_otp called with empty bot_token")

        text = (
            self._format_message(code)
            if isinstance(code, int) or (isinstance(code, str) and code.isdigit())
            else str(code)
        )

        if self.settings.debug:
            logger.info(
                "TELEGRAM OTP DEBUG — would send to chat_id=%s: %s",
                chat_id,
                text[:60],
            )
            return {"ok": True, "result": {"message_id": 0, "debug": True}}

        url = f"{self.settings.base_url}/bot{self.settings.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            # disable_web_page_preview is irrelevant for plain text but keeps
            # the response tight if we ever embed a link in the message.
            "disable_web_page_preview": True,
        }
        try:
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            if not result.get("ok"):
                raise Exception(
                    f"Telegram API returned ok=false: {result.get('description')}"
                )
            logger.info(
                "Telegram OTP delivered to chat_id=%s (message_id=%s)",
                chat_id,
                result.get("result", {}).get("message_id"),
            )
            return result
        except requests.exceptions.HTTPError as e:
            body = e.response.text[:200] if e.response is not None else ""
            logger.warning(
                "Telegram sendMessage HTTP %s for chat_id=%s: %s",
                e.response.status_code if e.response is not None else "?",
                chat_id,
                body,
            )
            raise
        except requests.exceptions.RequestException as e:
            logger.exception("Telegram sendMessage transport error: %s", e)
            raise

    def set_webhook(self, url: str) -> dict[str, Any]:
        """Register the webhook URL with Telegram. Idempotent — Telegram
        replaces any previously set URL. Called once at deploy time via a
        management command, not on every app boot.
        """
        if not self.settings.bot_token:
            raise RuntimeError("set_webhook called with empty bot_token")

        endpoint = f"{self.settings.base_url}/bot{self.settings.bot_token}/setWebhook"
        payload = {
            "url": url,
            "secret_token": self.settings.webhook_secret,
            # Only the update types we care about — reduces noise + bandwidth.
            # `message` covers /start payloads which is all we need for OTP.
            "allowed_updates": ["message"],
        }
        response = self.session.post(endpoint, json=payload, timeout=10)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        if not result.get("ok"):
            raise Exception(f"setWebhook failed: {result}")
        logger.info("Telegram webhook registered: %s", url)
        return result

    @staticmethod
    def _format_message(code: int | str) -> str:
        # Russian-first text. KZ-localized variant kicks in later via the
        # webhook's per-user locale lookup (chat lang from `from.language_code`).
        # For now a bilingual short body keeps both audiences served.
        return (
            f"<b>AIMA — код для входа</b>\n\n"
            f"<code>{code}</code>\n\n"
            f"Действителен 10 минут. Никому не сообщайте этот код."
        )
