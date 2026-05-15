"""STANDBY SMS PROVIDER — Twilio.

Not active in production. SMSC.kz is the primary provider; this module is
preserved for fast switch-over if SMSC delivery degrades (e.g. operator
blocks unbranded sender even after retry, or account suspended). To activate:

    1. Set TWILIO__ACCOUNT_SID, TWILIO__AUTH_TOKEN, TWILIO__SENDER=AIMA
       (and optionally TWILIO__MESSAGING_SERVICE_SID) in Railway env.
    2. In `src/api/containers.py`, swap the `sms_client` provider line to use
       `NotificationClientSMSTwilio` (see commented line there).
    3. Redeploy.
"""

import logging
from typing import Any

import httpx

from clients.notification.settings import TwilioSettings

logger = logging.getLogger(__name__)


class TwilioSMSClient:
    """SMS via Twilio REST API. Standby provider — see module docstring."""

    API_VERSION = "2010-04-01"
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(self, settings: TwilioSettings):
        self.settings = settings
        self.base_url = (
            f"https://api.twilio.com/{self.API_VERSION}/Accounts/{settings.account_sid}/Messages.json"
        )
        self.auth = (settings.account_sid, settings.auth_token)
        logger.info(
            "TwilioSMSClient initialized (account=%s..., sender=%s, messaging_service=%s)",
            settings.account_sid[:8],
            settings.sender,
            settings.messaging_service_sid or "—",
        )

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Normalize to E.164 (+77071234567)."""
        cleaned = "".join(filter(lambda c: c.isdigit() or c == "+", phone))
        if cleaned.startswith("+"):
            return cleaned
        digits = "".join(filter(str.isdigit, cleaned))
        if digits.startswith("8") and len(digits) == 11:
            return "+7" + digits[1:]
        if digits.startswith("7") and len(digits) == 11:
            return "+" + digits
        if len(digits) == 10:
            return "+7" + digits
        return "+" + digits

    def send_sms(self, phone: str, message: str, sender: str | None = None) -> dict[str, Any]:
        """Send SMS via Twilio. Returns Twilio message resource on success."""
        to = self.normalize_phone(phone)

        data: dict[str, str] = {"To": to, "Body": message}
        # Prefer Messaging Service SID if configured (handles sender pool, retries,
        # automatic alpha-sender selection per destination country).
        if self.settings.messaging_service_sid:
            data["MessagingServiceSid"] = self.settings.messaging_service_sid
        else:
            data["From"] = sender or self.settings.sender

        if self.settings.debug:
            logger.info("TWILIO DEBUG — would send to %s: %s", to, message[:80])
            return {"sid": "DEBUG", "status": "queued", "to": to}

        logger.info("Attempting Twilio SMS send to %s (from=%s)", to, data.get("From") or data.get("MessagingServiceSid"))

        try:
            response = httpx.post(
                self.base_url,
                data=data,
                auth=self.auth,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as e:
            logger.exception("Twilio network error sending to %s: %s", to, e)
            raise

        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text[:300]}
            code = body.get("code")
            msg = body.get("message", response.text[:200])
            logger.error("Twilio rejected SMS to %s: HTTP %s code=%s — %s", to, response.status_code, code, msg)
            raise Exception(f"Twilio error {code}: {msg}")

        result = response.json()
        logger.info(
            "Twilio SMS accepted to %s (sid=%s, status=%s, price=%s %s)",
            to,
            result.get("sid"),
            result.get("status"),
            result.get("price") or "pending",
            result.get("price_unit") or "",
        )
        # Map Twilio response to a shape compatible with SMSCClient.send_sms callers.
        return {
            "id": result.get("sid"),
            "status": result.get("status"),
            "cost": result.get("price"),
            "raw": result,
        }
