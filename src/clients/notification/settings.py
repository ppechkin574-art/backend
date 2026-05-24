from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramBotSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    token: str
    chat_id: str


class EmailClientSettings(BaseSettings):
    """Resend HTTP API настройки.

    Используется HTTP API вместо SMTP, потому что Railway (и большинство cloud-провайдеров)
    блокируют исходящий SMTP-трафик. См. TECH_DEBT.md п. 7.

    `extra="ignore"` — чтобы старые SMTP-переменные (email/password/smtp_server/port)
    не ломали инициализацию, если они остались в env после миграции с SMTP.
    """

    model_config = SettingsConfigDict(extra="ignore")

    api_key: str
    from_email: str = "onboarding@resend.dev"
    from_name: str = "AIMA"


class SMSCSettings(BaseSettings):
    login: str
    key: str
    sender: str | None = None
    debug: bool = False


class TwilioSettings(BaseSettings):
    """Twilio SMS gateway settings.

    Primary SMS provider for production. Either `messaging_service_sid` (preferred)
    or `sender` must be set. `sender` is the alphanumeric Sender ID (e.g. `AIMA`,
    max 11 chars, no Cyrillic) or a Twilio phone number in E.164.
    """

    model_config = SettingsConfigDict(extra="ignore")

    account_sid: str
    auth_token: str
    sender: str = "AIMA"
    messaging_service_sid: str | None = None
    debug: bool = False


class WazzupSettings(BaseSettings):
    api_key: str
    channel_id: str
    template_id: str
    base_url: str = "https://api.wazzup24.com"
    debug: bool = False


class TelegramOtpSettings(BaseSettings):
    """Self-hosted Telegram-bot OTP delivery for users on broken SMS routes
    (Beeline KZ sender-ID still pending registration at SMSC). Configured
    via @BotFather → bot token; webhook signed with a shared secret so a
    third party who learns the bot's webhook URL can't forge updates.

    Empty token / debug=true disables the channel — chain falls back to
    SMS-only as before. This keeps the rollout zero-risk for existing
    Tele2/Altel users.
    """

    model_config = SettingsConfigDict(extra="ignore")

    bot_token: str = ""
    bot_username: str = ""
    # Sent back by Telegram in `X-Telegram-Bot-Api-Secret-Token` header on
    # every webhook POST after we register it via setWebhook(secret_token=...).
    # Constant-time comparison in the handler; if the header is missing or
    # mismatched the update is dropped.
    webhook_secret: str = ""
    base_url: str = "https://api.telegram.org"
    debug: bool = False
