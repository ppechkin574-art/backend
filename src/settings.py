from pydantic_settings import BaseSettings, SettingsConfigDict

from clients import TelegramBotSettings
from clients.agent_webhook.settings import AgentWebhookSettings
from clients.apple.settings import AppleOAuthSettings
from clients.firebase.settings import FirebaseSettings
from clients.freedom_pay.settings import FreedomPaySettings
from clients.google.settings import GoogleOAuthSettings
from clients.identity_provider import KeycloakSettings
from clients.media_storage import MinioSettings
from clients.notification.settings import (
    EmailClientSettings,
    SMSCSettings,
    TelegramOtpSettings,
    TwilioSettings,
    WazzupSettings,
)
from database import DatabaseSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    redis_url: str
    telegram_bot: TelegramBotSettings
    keycloak: KeycloakSettings
    database: DatabaseSettings
    minio: MinioSettings
    allowed_origins: str
    freedom_pay: FreedomPaySettings
    google_oauth: GoogleOAuthSettings
    apple_oauth: AppleOAuthSettings
    email_client: EmailClientSettings
    smsc: SMSCSettings
    # Optional: only constructed if TWILIO__* env vars are set. Twilio is a
    # standby SMS provider — see clients/notification/twilio_client.py.
    twilio: TwilioSettings | None = None
    firebase: FirebaseSettings = FirebaseSettings()
    wazzup: WazzupSettings
    # Optional: Telegram-bot OTP fallback. Empty bot_token disables the
    # channel; chain falls back to SMS-only.
    telegram_otp: TelegramOtpSettings = TelegramOtpSettings()
    upload_base_dir: str
    file_base_url: str
    cloudflare_customer_code: str
    # Optional: 24/7 agent executor webhook. Blank/disabled until the
    # executor service exists — see AgentWebhookSettings.
    agent_webhook: AgentWebhookSettings = AgentWebhookSettings()
