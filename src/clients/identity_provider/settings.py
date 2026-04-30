from pydantic_settings import BaseSettings


class KeycloakAdminSettings(BaseSettings):
    server_url: str
    username: str
    password: str
    realm_name: str
    user_realm_name: str
    client_id: str
    verify: bool = True


class KeycloakOpenIdSettings(BaseSettings):
    server_url: str
    realm_name: str
    client_id: str
    client_secret_key: str
    verify: bool = True


class KeycloakSettings(BaseSettings):
    admin: KeycloakAdminSettings
    open_id: KeycloakOpenIdSettings
