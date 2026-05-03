from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    uri: str
