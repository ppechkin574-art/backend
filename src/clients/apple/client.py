import base64
import binascii
import logging
import time
from urllib.parse import urlencode

import jwt
import requests
from jwt import PyJWKClient

from .settings import AppleOAuthSettings

logger = logging.getLogger(__name__)


class AppleOAuthClient:
    def __init__(self, settings: AppleOAuthSettings):
        self.settings = settings
        self.jwks_client = PyJWKClient("https://appleid.apple.com/auth/keys")
        self.private_key_content: str | None = None

    def _load_private_key(self) -> str:
        """Resolve the Apple .p8 contents from one of two env-driven sources.

        Preference order:
          1. APPLE_OAUTH__PRIVATE_KEY_PEM — raw PEM contents OR a base64
             encoding of the PEM. Works on Railway without a volume.
          2. APPLE_OAUTH__PRIVATE_KEY_FILE — file path inside the container,
             requires Volume mount (legacy).

        Cached after first successful load.
        """
        if self.private_key_content is not None:
            return self.private_key_content

        pem_inline = (self.settings.private_key_pem or "").strip()
        if pem_inline:
            self.private_key_content = self._decode_pem(pem_inline)
            return self.private_key_content

        if self.settings.private_key_file:
            try:
                with open(self.settings.private_key_file) as f:
                    self.private_key_content = f.read()
                return self.private_key_content
            except FileNotFoundError:
                logger.exception(
                    "Apple private key file not found: %s",
                    self.settings.private_key_file,
                )
                raise
            except Exception as e:
                logger.exception("Error reading Apple private key: %s", e)
                raise

        raise ValueError(
            "Apple OAuth is not configured: set APPLE_OAUTH__PRIVATE_KEY_PEM "
            "(inline / base64) or APPLE_OAUTH__PRIVATE_KEY_FILE (mounted .p8)."
        )

    @staticmethod
    def _decode_pem(value: str) -> str:
        """If `value` already looks like a PEM (begins with '-----BEGIN'),
        return as-is. Otherwise treat it as base64(PEM) and decode."""
        if value.lstrip().startswith("-----BEGIN"):
            return value
        try:
            return base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(
                "APPLE_OAUTH__PRIVATE_KEY_PEM is neither raw PEM nor valid base64."
            ) from exc

    def generate_client_secret(self) -> str:
        """Генерирует JWT client secret для Apple OAuth"""
        private_key = self._load_private_key()
        now = int(time.time())
        payload = {
            "iss": self.settings.team_id,
            "iat": now,
            "exp": now + 3600,
            "aud": "https://appleid.apple.com",
            "sub": self.settings.client_id,
        }

        headers = {"kid": self.settings.key_id, "alg": "ES256"}

        try:
            client_secret = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
            return client_secret
        except Exception as e:
            logger.exception("Failed to generate Apple client secret: %s", e)
            raise ValueError(f"Failed to generate client secret: {e}")

    def exchange_code_for_tokens(self, code: str) -> dict:
        """Обменивает код авторизации на токены"""
        url = "https://appleid.apple.com/auth/token"

        try:
            client_secret = self.generate_client_secret()
        except Exception as e:
            raise ValueError(f"Failed to generate client secret: {e}")

        data = {
            "client_id": self.settings.client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.settings.redirect_uri,
        }

        try:
            response = requests.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )

            if response.status_code != 200:
                logger.exception(
                    "Apple token exchange failed: %s %s",
                    response.status_code,
                    response.text,
                )
                raise ValueError(f"Apple token exchange failed: {response.status_code} {response.text}")

            return response.json()

        except requests.exceptions.Timeout:
            logger.exception("Apple OAuth token exchange timeout")
            raise ValueError("Apple OAuth timeout - please try again")
        except requests.exceptions.RequestException as e:
            logger.exception("Apple OAuth network error: %s", e)
            raise ValueError(f"Apple OAuth network error: {e}")

    def verify_id_token(self, id_token: str) -> dict:
        """Безопасная верификация Apple ID token с проверкой подписи и диагностикой."""
        try:
            header = jwt.get_unverified_header(id_token)
            alg = header.get("alg")
            kid = header.get("kid")
            logger.debug("Apple id_token header: alg=%s kid=%s", alg, kid)

        except Exception as e:
            logger.exception("Failed to read id_token header")
            raise ValueError(f"Invalid Apple id_token header: {e}")

        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(id_token)
        except Exception as e:
            logger.exception("Failed to fetch JWK signing key for kid=%s", kid)
            raise ValueError(f"Failed to fetch Apple JWKS key (kid={kid}): {e}")

        allowed_algs = [alg] if alg else ["ES256"]
        try:
            payload = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=allowed_algs,
                audience=self.settings.client_id,
                issuer="https://appleid.apple.com",
            )

        except jwt.InvalidAlgorithmError as e:
            logger.warning(
                "InvalidAlgorithmError: token alg=%s allowed=%s, header=%s",
                alg,
                allowed_algs,
                header,
            )
            raise ValueError(f"Invalid Apple ID token algorithm: {e}")
        except jwt.ExpiredSignatureError:
            logger.warning("Apple ID token expired")
            raise ValueError("Apple ID token has expired")
        except jwt.PyJWTError as e:
            logger.warning("Invalid Apple ID token: %s; header=%s", e, header)
            raise ValueError(f"Invalid Apple ID token: {e}")
        except Exception as e:
            logger.exception("Apple ID token verification unexpected error")
            raise ValueError(f"Apple ID token verification failed: {e}")

        exp = payload.get("exp", 0)
        if exp and exp < int(time.time()):
            raise ValueError("Apple ID token has expired")

        return payload

    def build_authorize_url(self, state: str, scope: str = "name email") -> str:
        """Строит URL для авторизации через Apple"""
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "response_mode": "form_post",
        }
        return f"https://appleid.apple.com/auth/authorize?{urlencode(params)}"
