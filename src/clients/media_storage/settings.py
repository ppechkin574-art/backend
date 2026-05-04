from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings


class MinioSettings(BaseSettings):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    expires: timedelta = Field(default=timedelta(minutes=30))
    public_endpoint: str | None = None
    public_secure: bool = True
