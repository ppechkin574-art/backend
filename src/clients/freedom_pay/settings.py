from pydantic_settings import BaseSettings


class FreedomPaySettings(BaseSettings):
    merchant_id: str
    secret: str
    api_url: str
    payment_page: str
    callback_url: str
