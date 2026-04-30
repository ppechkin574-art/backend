import json
import logging
import secrets
import string
from typing import Any

from auth.dtos.auth import OAuthProviders
from auth.dtos.users import UserCreateDTO, UserQueryDTO
from auth.exceptions import UserNotFoundError
from auth.repositories.users import UserRepositoryInterface
from clients.apple.client import AppleOAuthClient
from clients.google.client import GoogleOAuthClient

logger = logging.getLogger(__name__)


class OAuthHelper:
    def __init__(
        self,
        users_repository: UserRepositoryInterface,
        google_client: GoogleOAuthClient,
        apple_client: AppleOAuthClient,
    ):
        self._users = users_repository
        self.clients = {
            OAuthProviders.GOOGLE: google_client,
            OAuthProviders.APPLE: apple_client,
        }

    def get_client(self, provider: OAuthProviders):
        client = self.clients.get(provider)
        if not client:
            raise ValueError(f"Unsupported OAuth provider: {provider}")
        return client

    def handle_oauth_user(self, email: str, name: str, provider: OAuthProviders) -> dict[str, Any]:
        """Унифицированная логика обработки OAuth пользователя"""
        try:
            user = self._users.get(UserQueryDTO(email=email))
            logger.info("Existing user found via %s: %s", provider, user.id)

            if not user.is_active:
                logger.info("Activating previously inactive user: %s", user.id)
                self._users.set_active(user.id, True)

            tokens = self._users.create_oauth_tokens(email)

        except UserNotFoundError:
            temp_password = self._generate_secure_password()

            user_create = UserCreateDTO(
                email=email,
                name=name.strip() or email.split("@")[0],
                phone=None,
                password=temp_password,
                role="student",
                is_active=True,
            )

            user = self._users.create(user_create)
            logger.info("New user created via %s: %s", provider, user.id)

            self._users.set_active(user.id, True)
            logger.info("New %s user activated: %s", provider, user.id)

            tokens = self._users.create_tokens(login=email, password=temp_password)

        return tokens

    def _generate_secure_password(self) -> str:
        """Генерация безопасного временного пароля"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(20))

    def get_authorization_url(self, provider: OAuthProviders, state: str) -> str:
        """Получение URL для авторизации"""
        client = self.get_client(provider)

        return client.build_authorize_url(state=state)

    def get_frontend_redirect(self, provider: OAuthProviders) -> str:
        """Получение redirect URL по умолчанию"""
        client = self.get_client(provider)

        return client.settings.frontend_redirect

    def extract_user_info(self, provider: OAuthProviders, code: str) -> tuple[str, str]:
        """Унифицированное извлечение информации о пользователе"""
        client = self.get_client(provider)

        token_response = client.exchange_code_for_tokens(code)
        id_token = token_response.get("id_token")

        if not id_token:
            raise ValueError(f"No id_token returned from {provider}")

        payload = client.verify_id_token(id_token)
        email = payload.get("email")

        if not email:
            raise ValueError(f"{provider} token doesn't contain email")

        name = self._extract_name_from_payload(provider, payload, email)

        return email, name

    def _extract_name_from_payload(self, provider: OAuthProviders, payload: dict, email: str) -> str:
        if provider == OAuthProviders.GOOGLE:
            return payload.get("name") or email.split("@")[0]

        elif provider == OAuthProviders.APPLE:
            name_claim = payload.get("name")
            if name_claim and isinstance(name_claim, str):
                try:
                    name_data = json.loads(name_claim)
                    first_name = name_data.get("firstName", "")
                    last_name = name_data.get("lastName", "")
                    return f"{first_name} {last_name}".strip()
                except Exception:
                    return name_claim
            return email.split("@")[0]

        return email.split("@")[0]
