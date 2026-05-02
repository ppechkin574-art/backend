from pydantic_settings import BaseSettings


class TelegramBotSettings(BaseSettings):
    token: str
    chat_id: str


class EmailClientSettings(BaseSettings):
    """Resend HTTP API настройки.

    Используется HTTP API вместо SMTP, потому что Railway (и большинство cloud-провайдеров)
    блокируют исходящий SMTP-трафик. См. TECH_DEBT.md п. 7.
    """

    api_key: str
    from_email: str = "onboarding@resend.dev"
    from_name: str = "AIMA"


class SMSCSettings(BaseSettings):
    login: str
    key: str
    sender: str | None = None
    debug: bool = False


class WazzupSettings(BaseSettings):
    api_key: str
    channel_id: str
    template_id: str
    base_url: str = "https://api.wazzup24.com"
    debug: bool = False
