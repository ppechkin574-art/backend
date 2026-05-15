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
