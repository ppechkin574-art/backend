from pydantic_settings import BaseSettings


class FreedomPaySettings(BaseSettings):
    merchant_id: str
    secret: str
    api_url: str
    payment_page: str
    callback_url: str
    # "1" while the merchant is in test mode (current default).  Switch to "0"
    # via Railway env (FREEDOM_PAY__TESTING_MODE=0) the same day the merchant
    # is moved to production by FreedomPay support — leaving "1" on a live
    # merchant is rejected by their backend.
    testing_mode: str = "1"
