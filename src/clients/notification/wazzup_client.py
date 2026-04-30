import logging
from typing import Any

import requests

from clients.notification.settings import WazzupSettings

logger = logging.getLogger(__name__)


class WazzupClient:
    def __init__(self, wazzup_settings: WazzupSettings):
        self.settings = wazzup_settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            }
        )
        logger.info("WazzupClient initialized with channel: %s", self.settings.channel_id)

    def _make_request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            url = f"{self.settings.base_url}/{method}"

            if self.settings.debug:
                logger.info(
                    "WAZZUP DEBUG - Simulation: %s -> %s...",
                    payload.get("chatId"),
                    payload.get("message", {}).get("text", "")[:50],
                )
                return {
                    "id": "debug_message_id",
                    "status": "sent",
                    "timestamp": "2024-01-01T00:00:00Z",
                }

            logger.debug("Wazzup Request: %s | Payload: %s", url, payload)

            response = self.session.post(url, json=payload, timeout=30)
            logger.debug("Wazzup Response status: %s", response.status_code)
            logger.debug("Wazzup Response text: %s...", response.text[:200])

            response.raise_for_status()
            result = response.json()

            logger.debug("Wazzup API response: %s", result)
            return result

        except requests.exceptions.RequestException as e:
            logger.exception("Wazzup Network error: %s", str(e))
            if hasattr(e, "response") and e.response is not None:
                logger.exception("Response: %s", e.response.text[:200])
            raise
        except Exception as e:
            logger.exception("Wazzup Unexpected error: %s", str(e))
            raise

    def normalize_phone(self, phone: str) -> str:
        original_phone = phone
        cleaned = "".join(filter(str.isdigit, phone))

        logger.debug("Phone normalization: %s -> %s", original_phone, cleaned)

        if cleaned.startswith("8") and len(cleaned) == 11:
            return "7" + cleaned[1:]
        elif cleaned.startswith("+7") and len(cleaned) == 12:
            return cleaned[1:]
        elif len(cleaned) == 10 and cleaned.startswith("7"):
            return "7" + cleaned
        elif len(cleaned) == 11 and cleaned.startswith("7"):
            return cleaned
        else:
            logger.warning("Unexpected phone format: %s -> %s", phone, cleaned)
            result = cleaned

        logger.debug("Normalized result: %s", result)
        return result

    def send_message(self, phone: str, message: str) -> dict[str, Any]:
        try:
            normalized_phone = self.normalize_phone(phone)

            payload = {
                "channelId": self.settings.channel_id,
                "templateId": self.settings.template_id,
                "chatType": "whatsapp",
                "chatId": normalized_phone,
                "templateValues": [message],
            }

            logger.info("Attempting WhatsApp send to %s", normalized_phone)
            logger.debug("Wazzup payload: %s", payload)

            result = self._make_request("v3/message", payload)

            if "error" in result:
                error_code = result.get("error_code", "unknown")
                error_msg = result.get("error", "Unknown error")
                logger.exception("Wazzup Error %s: %s", error_code, error_msg)
                raise Exception(f"Wazzup error {error_code}: {error_msg}")

            if self.settings.debug:
                logger.info(
                    "WAZZUP DEBUG - Simulated send to %s (ID: %s)",
                    phone,
                    result.get("id", "N/A"),
                )
            else:
                logger.info(
                    "WhatsApp message sent successfully to %s (ID: %s)",
                    phone,
                    result.get("id", "N/A"),
                )

            return result

        except Exception as e:
            logger.exception("Failed to send WhatsApp message to %s: %s", phone, str(e))
            raise

    # def get_balance(self) -> float:
    #     """Получает текущий баланс аккаунта"""
    #     try:
    #         url = f"{self.settings.base_url}/v3/balance"
    #         response = self.session.get(url)
    #         response.raise_for_status()
    #         result = response.json()
    #         return float(result.get("balance", 0))
    #     except Exception as e:
    #         logger.exception("Failed to get Wazzup balance: %s", str(e))
    #         return 0.0
