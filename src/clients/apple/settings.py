from pydantic_settings import BaseSettings, SettingsConfigDict


class AppleOAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    client_id: str
    team_id: str
    key_id: str
    private_key_file: str
    redirect_uri: str
    frontend_redirect: str
