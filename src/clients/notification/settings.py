from pydantic_settings import BaseSettings


class TelegramBotSettings(BaseSettings):
    token: str
    chat_id: str


class EmailClientSettings(BaseSettings):
    email: str
    password: str
    smtp_server: str = "smtp.gmail.com"
    port: int = 587


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
