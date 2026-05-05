from pydantic_settings import BaseSettings, SettingsConfigDict


class AppleOAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    client_id: str
    team_id: str
    key_id: str
    redirect_uri: str
    frontend_redirect: str
    # One of these two must be set:
    #   private_key_file:  path to a .p8 file inside the container (legacy
    #                      Volume-based deployment).
    #   private_key_pem:   raw PEM contents OR base64(PEM) — works on Railway
    #                      without a volume. Preferred.
    private_key_file: str | None = None
    private_key_pem: str | None = None
