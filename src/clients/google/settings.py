from pydantic_settings import BaseSettings


class GoogleOAuthSettings(BaseSettings):
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_redirect: str

    android_client_id: str | None = None
    ios_client_id: str | None = None

    @property
    def trusted_audiences(self) -> list[str]:
        """Все client_id, чьи id_token бэк готов принимать (web + mobile)."""
        return [v for v in (self.client_id, self.android_client_id, self.ios_client_id) if v]
