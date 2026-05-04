import logging
from urllib.parse import urlencode

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from .settings import GoogleOAuthSettings

logger = logging.getLogger(__name__)


class GoogleOAuthClient:
    def __init__(self, settings: GoogleOAuthSettings):
        self.settings = settings

    def exchange_code_for_tokens(self, code: str) -> dict:
        url = "https://oauth2.googleapis.com/token"

        data = {
            "code": code,
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "redirect_uri": self.settings.redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            resp = requests.post(url=url, data=data, headers={"Accept": "application/json"}, timeout=30)
            resp.raise_for_status()

            return resp.json()

        except requests.exceptions.Timeout:
            logger.exception("Google OAuth token exchange timeout")
            raise ValueError("Google OAuth timeout - please try again")
        except requests.exceptions.RequestException as e:
            logger.exception("Google OAuth network error: %s", e)
            raise ValueError(f"Google OAuth network error: {e}")
        except Exception as e:
            logger.exception("Google OAuth token exchange failed: %s", e)
            raise ValueError(f"Google OAuth failed: {e}")

    def verify_id_token(self, id_token_str: str) -> dict:
        """
        Возвращает payload (dict) после верификации id_token.
        Audience-проверка проходит, если id_token подписан на любой из
        client_id (web/android/ios) — мобила шлёт токен от своего нативного
        клиента, web flow — от web-клиента.
        """
        try:
            payload = google_id_token.verify_oauth2_token(
                id_token_str, google_requests.Request()
            )
            aud = payload.get("aud")
            if aud not in self.settings.trusted_audiences:
                raise ValueError(
                    f"Token audience '{aud}' is not in trusted client_ids"
                )
            return payload

        except ValueError as e:
            logger.warning("Invalid Google ID token: %s", e)
            raise ValueError(f"Invalid Google ID token: {e}")
        except Exception as e:
            logger.exception("Google ID token verification error: %s", e)
            raise ValueError(f"Google ID token verification failed: {e}")

    def build_authorize_url(self, state: str, scope: str = "openid email profile") -> str:
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
