from pydantic_settings import BaseSettings, SettingsConfigDict

from clients import TelegramBotSettings
from clients.apple.settings import AppleOAuthSettings
from clients.firebase.settings import FirebaseSettings
from clients.freedom_pay.settings import FreedomPaySettings
from clients.google.settings import GoogleOAuthSettings
from clients.identity_provider import KeycloakSettings
from clients.media_storage import MinioSettings
from clients.notification.settings import (
    EmailClientSettings,
    SMSCSettings,
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
    firebase: FirebaseSettings = FirebaseSettings()
    wazzup: WazzupSettings
    upload_base_dir: str
    file_base_url: str
    cloudflare_customer_code: str
