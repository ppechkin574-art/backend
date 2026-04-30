import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Protocol

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
    WazzupSettings,
)
from clients.notification.sms_client import SMSCClient
from clients.notification.template_loader import TemplateLoader
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


class PersonalGmailClient:
    """Клиент для отправки через Gmail"""

    def __init__(self, email_settings: EmailClientSettings):
        self.email = email_settings.email
        self.password = email_settings.password
        self.smtp_server = email_settings.smtp_server
        self.port = email_settings.port
        self.template_loader = TemplateLoader()

        if not self.email or not self.password:
            raise ValueError("Email and password must be provided")

        logger.info("EmailClient initialized for %s", self.email)

    def send_email(self, email_dto: EmailMessageDTO) -> None:
        try:
            msg = MIMEMultipart()
            msg["From"] = f"Lumi <{self.email}>"
            msg["To"] = email_dto.to
            msg["Subject"] = email_dto.subject
            msg["Date"] = formatdate(localtime=True)

            # 🔧 antispam headers
            msg["X-Priority"] = "1"
            msg["X-Mailer"] = "Lumi Mail System"
            msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
            msg["Precedence"] = "bulk"
            msg["Auto-Submitted"] = "auto-generated"

            html_content = self.template_loader.render_template(
                "email_verification", verification_code=email_dto.message
            )

            msg.attach(MIMEText(html_content, "html"))

            # alternative (fallback)
            text_content = f"""
                Код подтверждения Lumi: {email_dto.message}

                Введите этот код для завершения регистрации.
                Код действителен в течение 1 часа.

                Если вы не запрашивали регистрацию, проигнорируйте это письмо.

                С уважением,
                Команда Lumi App
                support@lumi-unt.kz
                """
            msg.attach(MIMEText(text_content, "plain"))

            with smtplib.SMTP_SSL(self.smtp_server, self.port) as server:
                server.login(self.email, self.password)
                server.send_message(msg)

            logger.info("Email sent successfully to %s", email_dto.to)

        except Exception as e:
            logger.exception("Failed to send email to %s: %s", email_dto.to, e)
            raise


class NotificationClientEmail:
    """Клиент для отправки email уведомлений"""

    def __init__(self, email_settings: EmailClientSettings):
        self.email_client = PersonalGmailClient(email_settings)
        logger.info("NotificationClientEmail initialized")

    def notify(self, message: NotificationMessageDTO) -> None:
        code = message.message.split(": ")[-1] if ": " in message.message else message.message
        email_dto = EmailMessageDTO(
            to=message.to,
            subject="Your Lumi Verification Code",
            message=code,
            from_email=self.email_client.email,
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

            formatted_message = f"Код подтверждения: {sms_text}"

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
        """Fallback: отправляем код в Telegram"""
        try:
            code = message.message.split(":")[-1].strip() if ":" in message.message else message.message

            telegram_message = (
                f"<b> 🔧 Wazzup недоступен</b>\n"
                f"<b>Пользователь не получил код подтверждения</b>\n\n"
                f"<b>Контакт:</b> {message.to}\n"
                f"<b>Код:</b> <code>{code}</code>\n\n"
                f"<b> ⚠️  Ошибка:</b> <code>{error_msg[:150]}</code>"
            )

            if self.telegram_client:
                telegram_notification = NotificationMessageDTO(
                    to="",
                    message=telegram_message,
                    platform=CodePlatform.TELEGRAM,
                )
                self.telegram_client.notify(telegram_notification)
                logger.info("Fallback message sent to Telegram for %s", message.to)
            else:
                logger.warning("WHATSAPP FALLBACK: %s", telegram_message)
                logger.info("Code for dev: %s (for %s)", code, message.to)

        except Exception as e:
            logger.exception("Failed to send fallback to Telegram: %s", e)
