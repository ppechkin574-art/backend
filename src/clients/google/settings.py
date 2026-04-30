from pydantic_settings import BaseSettings


class GoogleOAuthSettings(BaseSettings):
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_redirect: str
