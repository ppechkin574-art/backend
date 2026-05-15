import logging
from typing import Any

import requests

from clients.notification.settings import SMSCSettings

logger = logging.getLogger(__name__)


class SMSCClient:
    """Клиент для отправки SMS через SMSC.KZ"""

    BASE_URL = "https://smsc.kz/rest/"

    def __init__(self, smsc_settings: SMSCSettings):
        self.settings = smsc_settings
        self.session = requests.Session()
        logger.info("SMSCClient initialized with API key: %s...", self.settings.key[:10])
        logger.info("SMSC debug: %s, sender: %s", self.settings.debug, self.settings.sender)

    def _make_request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Базовый метод для API запросов"""
        try:
            url = f"{self.BASE_URL}{method}"

            if self.settings.debug:
                logger.info(
                    "SMSC DEBUG - Simulation: %s -> %s...",
                    payload.get("phones"),
                    payload.get("mes")[:50],
                )
                return {
                    "id": 999999,
                    "cnt": 1,
                    "cost": 14.0,
                    "balance": 100.0,
                    "status": "DEBUG_MODE",
                }

            # SMSC supports two auth modes: apikey (token) OR login+psw (account
            # password OR additional API password). Our `key` setting actually
            # holds an additional API password created in SMSC LK → Settings →
            # Аккаунт → дополнительные пароли (тип "API HTTP/S, SOAP, SMTP"),
            # so we must send it as `psw` together with `login`. Sending it
            # under `apikey` returns SMSC error 2 "authorise error".
            payload.update(
                {
                    "login": self.settings.login,
                    "psw": self.settings.key,
                    "fmt": 3,
                }
            )
            logger.debug("SMSC Request: %s | Payload: %s", url, payload)

            response = self.session.post(url, json=payload, timeout=30)
            logger.debug("SMSC Response status: %s", response.status_code)
            logger.debug("SMSC Response text: %s...", response.text[:200])

            response.raise_for_status()
            result = response.json()

            logger.debug("SMSC API response: %s", result)
            return result

        except requests.exceptions.RequestException as e:
            logger.exception("SMSC Network error: %s", str(e))
            if hasattr(e, "response") and e.response is not None:
                logger.exception("Response: %s", e.response.text)
            raise
        except Exception as e:
            logger.exception("SMSC Unexpected error: %s", str(e))
            raise

    def normalize_phone(self, phone: str) -> str:
        """Нормализует номер телефона для Казахстана"""
        original_phone = phone
        cleaned = "".join(filter(str.isdigit, phone))

        logger.debug("Phone normalization: %s -> %s", original_phone, cleaned)

        if cleaned.startswith("8") and len(cleaned) == 11:
            # 8 (707) 123-4567 -> 77071234567
            return "7" + cleaned[1:]
        elif cleaned.startswith("+7") and len(cleaned) == 12:
            # +7 (707) 123-4567 -> 77071234567
            return cleaned[1:]
        elif len(cleaned) == 10 and cleaned.startswith("7"):
            # 7071234567 -> 77071234567
            return "7" + cleaned
        elif len(cleaned) == 11 and cleaned.startswith("7"):
            # 77071234567
            return cleaned
        else:
            logger.warning("Unexpected phone format: %s -> %s", phone, cleaned)
            result = cleaned

        logger.debug("Normalized result: %s", result)
        return result

    def _build_payload(
        self,
        phone: str,
        message: str,
        sender: str | None,
    ) -> dict[str, Any]:
        """Builds SMSC `send/` payload.

        `translit=1` forces Cyrillic→Latin transliteration on SMSC side. Without
        it, KZ operators (Tele2/Altel especially) frequently reject Cyrillic
        transactional SMS as spam (Error 8 "can't to deliver"). With translit
        on, the message is delivered as ASCII, fitting in 1 segment and passing
        operator filters.

        Empty `sender` means we omit the field entirely so SMSC routes the SMS
        through its default operator-approved short number — the most reliable
        path for accounts without a custom approved Sender ID.
        """
        payload: dict[str, Any] = {
            "phones": phone,
            "mes": message,
            "charset": "utf-8",
            "translit": 1,
        }
        if sender:
            payload["sender"] = sender
        return payload

    def send_sms(self, phone: str, message: str, sender: str | None = None) -> dict[str, Any]:
        """Отправляет SMS сообщение с retry на Error 8 ("can't to deliver")."""
        try:
            normalized_phone = self.normalize_phone(phone)
            if len(normalized_phone) != 11 or not normalized_phone.startswith("77"):
                logger.exception("Invalid Qazaqstan phone format: %s", normalized_phone)
                raise ValueError(f"Invalid phone format: {normalized_phone}")

            # Sender precedence: explicit arg > settings > empty (SMSC default route).
            primary_sender = sender if sender is not None else self.settings.sender
            # Treat the legacy default "SMSC.KZ" as "no sender" — that name was
            # the root cause of Error 8 on Tele2/Altel. Empty sender forces SMSC
            # to pick its own delivery-approved short number.
            if primary_sender and primary_sender.strip().upper() in {"SMSC.KZ", "SMSC"}:
                primary_sender = None

            attempts: list[tuple[str, str | None]] = [
                ("primary", primary_sender),
            ]
            # If the primary attempt uses a custom sender, retry once with empty
            # sender on Error 8 — SMSC's default short number bypasses brand
            # filters and almost always delivers.
            if primary_sender:
                attempts.append(("fallback-default-route", None))

            last_error: Exception | None = None
            for label, attempt_sender in attempts:
                payload = self._build_payload(normalized_phone, message, attempt_sender)
                logger.info(
                    "SMSC send attempt=%s to %s sender=%r translit=1",
                    label,
                    normalized_phone,
                    attempt_sender or "<default>",
                )
                result = self._make_request("send/", payload)

                if "error" not in result:
                    logger.info(
                        "SMS sent successfully to %s (ID: %s, Cost: %s KZT, attempt=%s)",
                        phone,
                        result.get("id", "N/A"),
                        result.get("cost", "N/A"),
                        label,
                    )
                    return result

                error_code = result.get("error_code", "unknown")
                error_msg = result.get("error", "Unknown error")
                logger.error("SMSC attempt=%s Error %s: %s", label, error_code, error_msg)

                # Map SMSC error codes per https://smsc.kz/api/http/#errors
                if error_code == 2:
                    logger.error("🔐 Authorise error (login/psw/apikey/blocked IP)")
                elif error_code == 3:
                    logger.error("💸 Insufficient balance")
                elif error_code == 4:
                    logger.error("📛 Invalid sender name or IP not whitelisted")
                elif error_code == 7:
                    logger.error("📵 Invalid phone number")
                elif error_code == 8:
                    logger.warning("🚫 Operator rejected delivery (route/sender mismatch)")

                last_error = Exception(f"SMSC error {error_code}: {error_msg}")
                # Only retry on Error 8 (delivery rejection). Auth/balance/format
                # errors won't be fixed by changing sender, so bail out.
                if error_code != 8:
                    break

            raise last_error or Exception("SMSC send failed with no diagnostic")

        except Exception as e:
            logger.exception("Failed to send SMS to %s: %s", phone, str(e))
            raise

    # def get_balance(self) -> float:
    #     """Получает текущий баланс аккаунта"""
    #     try:
    #         result = self._make_request("balance", {})
    #         return float(result.get("balance", 0))
    #     except Exception as e:
    #         logger.exception("Failed to get SMSC balance: %s", str(e))
    #         return 0.0

    # def check_message_status(self, message_id: int, phone: str) -> dict[str, Any]:
    #     """Проверяет статус отправленного сообщения"""
    #     try:
    #         normalized_phone = self.normalize_phone(phone)
    #         params = {"phone": normalized_phone, "id": message_id}
    #         return self._make_request("status", params)
    #     except Exception as e:
    #         logger.exception("Failed to check message status %s: %s", message_id, str(e))
    #         return {}
