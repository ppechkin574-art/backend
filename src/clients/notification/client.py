import logging
from typing import Protocol

import httpx
import requests

from clients.notification.dtos import (
    CodePlatform,
    EmailMessageDTO,
    NotificationMessageDTO,
)
from clients.notification.settings import (
    EmailClientSettings,
    SMSCSettings,
    TelegramBotSettings,
    TwilioSettings,
    WazzupSettings,
)
from clients.notification.sms_client import SMSCClient
from clients.notification.template_loader import TemplateLoader
from clients.notification.twilio_client import TwilioSMSClient
from clients.notification.wazzup_client import WazzupClient

logger = logging.getLogger(__name__)


class NotificationClientInterface(Protocol):
    def notify(self, message: NotificationMessageDTO) -> None:
        """
        Notify user with a message.

        Args:
            message: Parameters for notification.
        """
        raise NotImplementedError


class ResendEmailClient:
    """Клиент для отправки email через Resend HTTP API.

    Заменил собой старый SMTP-клиент (PersonalGmailClient), потому что Railway и
    большинство cloud-провайдеров блокируют исходящий SMTP-трафик (порты 25/465/587).
    """

    API_URL = "https://api.resend.com/emails"
    REQUEST_TIMEOUT_SECONDS = 15

    def __init__(self, email_settings: EmailClientSettings):
        if not email_settings.api_key:
            raise ValueError("Resend API key must be provided (email_client__API_KEY)")

        self.api_key = email_settings.api_key
        self.from_email = email_settings.from_email
        self.from_name = email_settings.from_name
        self.template_loader = TemplateLoader()

        logger.info("ResendEmailClient initialized (from=%s)", self.from_email)

    def send_email(self, email_dto: EmailMessageDTO) -> None:
        html_content = self.template_loader.render_template(
            "email_verification", verification_code=email_dto.message
        )

        text_content = (
            f"Код подтверждения AIMA: {email_dto.message}\n\n"
            "Введите этот код для завершения регистрации.\n"
            "Код действителен в течение 1 часа.\n\n"
            "Если вы не запрашивали регистрацию, проигнорируйте это письмо.\n\n"
            "Команда AIMA"
        )

        payload = {
            "from": f"{self.from_name} <{self.from_email}>",
            "to": [email_dto.to],
            "subject": email_dto.subject,
            "html": html_content,
            "text": text_content,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                self.API_URL, headers=headers, json=payload, timeout=self.REQUEST_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as e:
            logger.exception("Resend HTTP error sending to %s: %s", email_dto.to, e)
            raise

        if response.status_code >= 400:
            logger.error(
                "Resend rejected message to %s: HTTP %s — %s",
                email_dto.to,
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        logger.info("Email sent successfully to %s (resend id=%s)", email_dto.to, response.json().get("id"))

    def send_alert_email(self, to: str, subject: str, html: str, text: str | None = None) -> None:
        """Send a plain text/HTML alert to ops (not an OTP template).

        Used for runtime alerts like "daily SMS cap exceeded" — distinct from
        `send_email` which always renders the OTP verification template.
        Failures here are LOGGED but NOT raised; an alert that fails to send
        must never break the request flow it was reporting on.
        """
        payload = {
            "from": f"{self.from_name} <{self.from_email}>",
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text or _strip_html(html),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                self.API_URL, headers=headers, json=payload, timeout=self.REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code >= 400:
                logger.error(
                    "Resend rejected alert email to %s: HTTP %s — %s",
                    to,
                    response.status_code,
                    response.text[:200],
                )
                return
            logger.info("Alert email sent to %s (subject=%r)", to, subject[:80])
        except httpx.HTTPError as e:
            logger.exception("Resend HTTP error sending alert to %s: %s", to, e)


def _mask_contact(contact: str) -> str:
    """Маскирует телефон/email для логов: +77012345678 → +770*****678"""
    if not contact:
        return "***"
    if "@" in contact:
        local, domain = contact.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if len(contact) > 6:
        return contact[:4] + "*" * (len(contact) - 6) + contact[-3:]
    return "***"


def _strip_html(html: str) -> str:
    """Very small HTML→text fallback for the email `text` part. We don't
    pull in beautifulsoup4 just for this — alerts use simple <p>/<ul>
    markup, regex is sufficient."""
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


# Алиас для обратной совместимости — старое имя класса
PersonalGmailClient = ResendEmailClient


class NotificationClientEmail:
    """Клиент для отправки email уведомлений (через Resend)"""

    def __init__(self, email_settings: EmailClientSettings):
        self.email_client = ResendEmailClient(email_settings)
        logger.info("NotificationClientEmail initialized")

    def send_alert(self, to: str, subject: str, html: str, text: str | None = None) -> None:
        """Делегирует на ResendEmailClient.send_alert_email — для рантайм-алёртов
        (SMS cap, abuse-detection, etc.). Отделено от `notify()` который шлёт
        только OTP по шаблону."""
        self.email_client.send_alert_email(to=to, subject=subject, html=html, text=text)

    def notify(self, message: NotificationMessageDTO) -> None:
        code = message.message.split(": ")[-1] if ": " in message.message else message.message
        email_dto = EmailMessageDTO(
            to=message.to,
            subject="Код подтверждения AIMA",
            message=code,
            from_email=self.email_client.from_email,
        )

        try:
            self.email_client.send_email(email_dto)
            logger.info("Email notification sent to %s", message.to)
        except Exception as e:
            logger.exception("Failed to send email notification to %s: %s", message.to, e)
            raise


class NotificationClientTelegram:
    def __init__(self, settings: TelegramBotSettings) -> None:
        self._settings = settings
        logger.info("NotificationClientTelegram initialized")

    def notify(self, message: NotificationMessageDTO) -> None:
        url = f"https://api.telegram.org/bot{self._settings.token}/sendMessage"
        payload = {
            "chat_id": self._settings.chat_id,
            "text": message.message,
            "parse_mode": "HTML",
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.exception("Failed to send Telegram notification: %s", response.text)
            else:
                logger.info("Telegram notification sent successfully")
        except Exception as e:
            logger.exception("Error sending Telegram notification: %s", e)


class NotificationClientSMS:
    """Клиент для отправки SMS уведомлений через SMSC.KZ"""

    def __init__(self, smsc_settings: SMSCSettings):
        self.sms_client = SMSCClient(smsc_settings)
        logger.info("NotificationClientSMS initialized")

    def notify(self, message: NotificationMessageDTO) -> None:
        """Отправляет SMS уведомление"""
        try:
            sms_text = message.message.split(":")[-1].strip() if ":" in message.message else message.message

            # SMSC.kz общее имя route на Tele2/Altel требует, чтобы бренд
            # назван в самом тексте (письмо менеджера SMSC от 15.05.2026).
            # С translit=1 это уйдёт как "AIMA: Kod podtverzhdeniya 847341".
            formatted_message = f"AIMA: Код подтверждения {sms_text}"

            result = self.sms_client.send_sms(phone=message.to, message=formatted_message)

            if self.sms_client.settings.debug:
                logger.info("SMS DEBUG - Notification simulated for %s", message.to)
            else:
                logger.info(
                    "SMS notification sent to %s (ID: %s)",
                    message.to,
                    result.get("id", "N/A"),
                )

        except Exception as e:
            logger.exception("Failed to send SMS notification to %s: %s", message.to, e)
            raise


class NotificationClientSMSTwilio:
    """SMS notifications via Twilio — STANDBY provider (not wired in container).

    See `clients/notification/twilio_client.py` module docstring for activation steps.
    """

    def __init__(self, twilio_settings: TwilioSettings):
        self.sms_client = TwilioSMSClient(twilio_settings)
        logger.info("NotificationClientSMSTwilio initialized")

    def notify(self, message: NotificationMessageDTO) -> None:
        try:
            sms_text = message.message.split(":")[-1].strip() if ":" in message.message else message.message
            formatted_message = f"Код подтверждения: {sms_text}"

            result = self.sms_client.send_sms(phone=message.to, message=formatted_message)

            if self.sms_client.settings.debug:
                logger.info("Twilio DEBUG — Notification simulated for %s", message.to)
            else:
                logger.info(
                    "Twilio SMS notification sent to %s (sid=%s, status=%s)",
                    message.to,
                    result.get("id"),
                    result.get("status"),
                )
        except Exception as e:
            logger.exception("Failed to send Twilio SMS to %s: %s", message.to, e)
            raise


class NotificationClientWhatsApp:
    """Клиент для отправки WhatsApp уведомлений через Wazzup"""

    def __init__(self, wazzup_settings: WazzupSettings, telegram_client=None):
        self.wazzup_client = WazzupClient(wazzup_settings)
        self.telegram_client = telegram_client
        logger.info("NotificationClientWhatsApp initialized")

    def notify(self, message: NotificationMessageDTO) -> None:
        """Отправляет WhatsApp уведомление"""
        try:
            whatsapp_text = message.message.split(":")[-1].strip() if ":" in message.message else message.message

            result = self.wazzup_client.send_message(phone=message.to, message=whatsapp_text)

            if self.wazzup_client.settings.debug:
                logger.info("WHATSAPP DEBUG - Notification simulated for %s", message.to)
            else:
                logger.info(
                    "WhatsApp notification sent to %s (ID: %s)",
                    message.to,
                    result.get("id", "N/A"),
                )

        except Exception as e:
            logger.exception("Failed to send WhatsApp notification to %s: %s", message.to, str(e))
            self._fallback_to_telegram(message, str(e))

    def _fallback_to_telegram(self, message: NotificationMessageDTO, error_msg: str) -> None:
        """Fallback: уведомляем ops о недоставленном коде (без самого кода)."""
        try:
            masked = _mask_contact(message.to)
            telegram_message = (
                f"<b>⚠️ Wazzup недоступен</b>\n"
                f"Пользователь не получил код подтверждения.\n\n"
                f"<b>Контакт:</b> {masked}\n"
                f"<b>Ошибка:</b> <code>{error_msg[:150]}</code>\n\n"
                f"Отправьте код вручную или попросите пользователя повторить запрос."
            )

            if self.telegram_client:
                telegram_notification = NotificationMessageDTO(
                    to="",
                    message=telegram_message,
                    platform=CodePlatform.TELEGRAM,
                )
                self.telegram_client.notify(telegram_notification)
                logger.warning("WhatsApp delivery failed for %s, ops notified via Telegram", masked)
            else:
                logger.warning("WhatsApp delivery failed for %s, no fallback channel configured", masked)

        except Exception as e:
            logger.exception("Failed to send fallback notification: %s", e)
