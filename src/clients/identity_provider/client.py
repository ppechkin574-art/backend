import logging
import secrets
import string
import time
from datetime import datetime
from typing import Protocol
from uuid import UUID

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from keycloak import KeycloakAdmin, KeycloakError, KeycloakOpenID
from pydantic import EmailStr

from clients.identity_provider.dtos import (
    KeycloakAccessTokenDTO,
    KeycloakCreateUserDTO,
    KeycloakUserDTO,
    KeycloakUserQueryDTO,
    KeycloakUserUpdateDTO,
)
from clients.identity_provider.exceptions import (
    EmailAlreadyExists,
    IdentityNotFound,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    NotVerifiedError,
)
from clients.identity_provider.settings import KeycloakSettings
from common.enums import PlanType
from utils.cache import CacheService, CacheStrategy
from utils.monitoring import log_info
from utils.validators import KZPhone

logger = logging.getLogger(__name__)


class IdentityProviderClientInterface(Protocol):
    def get_or_create(
        self, user: KeycloakCreateUserDTO
    ) -> tuple[KeycloakUserDTO, bool]:
        """
        Create user.

        Args:
            user: KeycloakCreateUserDTO.

        Returns:
            KeycloakUserDTO: Created user information or Existing user.
            bool: Is created

        Raises:
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def get(self, user: KeycloakUserQueryDTO) -> KeycloakUserDTO:
        """
        Get User.

        Args:
            user: Parameters to query user.

        Returns:
            KeycloakUserDTO: Found user information.

        Raises:
            IdentityNotFound
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def get_roles(self, user_id: UUID) -> list[str]:
        """
        Gets user's roles.

        Args:
            user_id: UUID of user.

        Returns:
            list[str]: User's roles.

        Raises:
            IdentityNotFound
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def delete(self, user_id: UUID) -> None:
        """
        Delete user.

        Args:
            user_id: ID of the user to delete.

        Raises:
            IdentityNotFound
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def set_active(self, user_id: UUID, active: bool) -> None:
        """
        Change active state of the user.

        Args:
            user_id: ID of the user to change active state to.
            active: Value to which active state will bi set.

        Raises:
            IdentityNotFound
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def create_tokens(
        self, login: KZPhone | EmailStr, password: str
    ) -> KeycloakAccessTokenDTO:
        """
        Create tokens for the user.

        Args:
            login: phone or email
            password: password

        Returns:
            KeycloakAccessTokenDTO: Tokens for the user.

        Raises:
            InvalidAccessTokenError: If access token is invalid.
            NotVerifiedAccount: If account not verified.
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def refresh_tokens(self, refresh_token: str) -> KeycloakAccessTokenDTO:
        """
        Refresh tokens for the user.

        Args:
            refresh_token: refresh_token

        Returns:
            KeycloakAccessTokenDTO: Tokens for the user.

        Raises:
            InvalidRefreshTokenError: If refresh token is invalid.
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def set_password(self, user_id: UUID, password: str) -> bool:
        """
        Change user password.

        Args:
            user_id: user_id
            password: password

        Raises:
            IdentityNotFound
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def get_user_sub_from_token(self, token: str) -> UUID:
        """
        Verify user token and gets user sub.

        Args:
            token: token

         Returns:
            UUID: User's sub from token.

        Raises:
            InvalidAccessTokenError
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def logout(self, refresh_token: str) -> None:
        """
        Logout user.

        Args:
            refresh_token: Refresh token

        Raises:
            InvalidRefreshTokenError
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def logout_all_sessions(self, user_id: UUID) -> None:
        """
        Revoke every active session/refresh token for the given user.

        Args:
            user_id: target user

        Raises:
            IdentityNotFound: If user not found.
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def update_user(self, user_id: UUID, data: KeycloakUserUpdateDTO) -> None:
        """
        Updates user by user_id.

        Args:
            user_id: user_id
            data: KeycloakUserUpdateDTO

        Raises:
            IdentityNotFound: If user not found.
            EmailAlreadyExists: If updating email already exists.
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def create_oauth_tokens(self, user_id: UUID) -> KeycloakAccessTokenDTO:
        """
        Create tokens for OAuth authentication.

        Args:
            user_id: UUID of user.

        Returns:
            KeycloakAccessTokenDTO: Tokens for the user.

        Raises:
            IdentityNotFound: If user not found.
            KeycloakError: In other cases of error.
        """
        raise NotImplementedError

    def update_user_subscription(
        self, user_id: UUID, plan: PlanType, expires_at: datetime | None = None
    ) -> None:
        """
        Обновить подписку пользователя в Keycloak

        Args:
            user_id: ID пользователя
            plan: Тип плана подписки
            expires_at: Дата окончания подписки (опционально)

        Raises:
            IdentityNotFound: Если пользователь не найден
            KeycloakError: При ошибке Keycloak
        """
        raise NotImplementedError


class IdentityProviderClientKeycloak:
    # Realm signing public key (PEM), cached at the CLASS level so it is
    # shared across all per-request instances and fetched from Keycloak
    # only once per process. Refreshed on signature failure (key rotation).
    # See _get_realm_public_key_pem / get_user_sub_from_token.
    _cached_public_key_pem: str | None = None

    def __init__(
        self,
        keycloak_settings: KeycloakSettings,
        cache_service: CacheService | None = None,
    ) -> None:
        self._keycloak_admin = KeycloakAdmin(**keycloak_settings.admin.model_dump())
        self._keycloak_openid = KeycloakOpenID(**keycloak_settings.open_id.model_dump())

        self._keycloak_settings = keycloak_settings
        self._client_id = keycloak_settings.open_id.client_id
        self._client_secret = keycloak_settings.open_id.client_secret_key
        self._base_url = keycloak_settings.open_id.server_url
        self._realm_name = keycloak_settings.open_id.realm_name
        # Used to invalidate the cached user profile (see UserRepositoryKeycloak)
        # whenever this client writes to a user — keeps the cache correct.
        self._cache = cache_service

        import requests

        self._session = requests.Session()

    def _invalidate_user_profile_cache(self, user_id: UUID) -> None:
        """Drop the cached profile for a user after a write.

        Keyed identically to the read cache in
        UserRepositoryKeycloak.get_user_from_token. A cache failure must
        never break the write it follows, so errors are swallowed.
        """
        if self._cache is None:
            return
        try:
            key = self._cache.make_key(
                CacheStrategy.USER, user_id=user_id, resource="profile"
            )
            self._cache.delete(key)
        except Exception as _e:
            logger.warning("Failed to invalidate user profile cache: %s", str(_e))

    # def _generate_username(
    #     self,
    #     email: str | None,
    #     phone: str | None,
    #     first_name: str | None,
    #     last_name: str | None,
    # ) -> str:
    #     """
    #     Генерация username по правилам:
    #     1. Если есть email -> username = часть до @
    #     2. Если нет email -> username = имя + рандомные символы
    #     """
    #     if email:
    #         username = email.split("@")[0]
    #         username = re.sub(r"[^a-zA-Z0-9._-]", "", username)
    #         return username

    #     name_parts = []
    #     if first_name:
    #         name_parts.append(first_name[0].lower())
    #     if last_name:
    #         name_parts.append(last_name.lower())

    #     base_username = (
    #         "".join(name_parts)
    #         if name_parts
    #         else phone.lstrip("+") if phone else "user"
    #     )

    #     base_username = re.sub(r"[^a-zA-Z0-9]", "", base_username)

    #     random_suffix = "".join(
    #         secrets.choice(string.ascii_lowercase + string.digits, k=4)
    #     )

    #     return f"{base_username}_{random_suffix}"

    def get_or_create(
        self, user: KeycloakCreateUserDTO
    ) -> tuple[KeycloakUserDTO, bool]:
        logger.info(
            "Creating or getting user: email=%s, phone=%s",
            user.email,
            user.attributes.phone,
        )

        try:
            if user.email:
                existing_user = self.get(KeycloakUserQueryDTO(email=user.email))
                logger.info("Existing user found by email: %s", existing_user.id)
                return existing_user, False
        except IdentityNotFound:
            pass

        try:
            if user.attributes.phone:
                existing_user = self.get(
                    KeycloakUserQueryDTO(phone=user.attributes.phone[0])
                )
                logger.info("Existing user found by phone: %s", existing_user.id)
                return existing_user, False
        except IdentityNotFound:
            pass

        if self._user_exists(phone=user.attributes.phone, email=user.email):
            raise IdentityNotFound("User already exists")

        logger.info(
            "User not found, creating new: email=%s, phone=%s",
            user.email,
            user.attributes.phone,
        )

        try:
            user_id = UUID(
                self._keycloak_admin.create_user(user.model_dump(mode="json"))
            )
            logger.info("User created successfully: %s", user_id)
            return self.get(KeycloakUserQueryDTO(id=user_id)), True
        except KeycloakError as _e:
            if _e.response_code == 409:
                logger.warning("User creation conflict, analyzing: %s", str(_e))

                error_msg = (
                    _e.error_message.decode()
                    if isinstance(_e.error_message, bytes)
                    else str(_e.error_message)
                )
                logger.info("Conflict error message: %s", error_msg)

                if "username" in error_msg.lower():
                    logger.warning("Username conflict detected for: %s", user.username)
                    raise IdentityNotFound("Username conflict, retry with new username")
                elif "email" in error_msg.lower():
                    try:
                        existing_user = self.get(KeycloakUserQueryDTO(email=user.email))
                        logger.info(
                            "Existing user found after email conflict: %s",
                            existing_user.id,
                        )
                        return existing_user, False
                    except IdentityNotFound:
                        logger.exception(
                            "Email conflict but user not found: %s", user.email
                        )
                        raise IdentityNotFound

                logger.exception("Unknown conflict type: %s", error_msg)
                raise IdentityNotFound

            logger.exception("Keycloak error creating user: %s", str(_e))
            raise

    # def complete_user_setup(self, user_id: str) -> None:
    #     """Завершает настройку пользователя в Keycloak."""
    #     try:
    #         user = self._keycloak_admin.get_user(user_id)

    #         user["requiredActions"] = []

    #         user["emailVerified"] = True

    #         if "attributes" not in user:
    #             user["attributes"] = {}

    #         if "phone" in user["attributes"]:
    #             user["attributes"]["phoneVerified"] = ["true"]

    #         self._keycloak_admin.update_user(user_id, user)
    #         logger.info("User setup completed for: %s", user_id)

    #     except Exception as e:
    #         logger.exception("Failed to complete user setup: %s", str(e))
    #         raise

    def get(self, user: KeycloakUserQueryDTO) -> KeycloakUserDTO:
        log_info(
            "Getting user",
            user_id=str(user.id) if user.id else None,
            email=user.email,
            phone=user.phone,
            username=user.username,
            action="get_user",
        )

        try:
            if user.id:
                logger.debug("Searching user by ID: %s", user.id)
                user_rep = self._keycloak_admin.get_user(str(user.id))
                logger.debug("User found by ID: %s", user_rep.get("id", "Unknown"))
            elif user.email:
                logger.debug("Searching by email: %s", user.email)
                users = self._keycloak_admin.get_users(
                    query={"email": user.email, "exact": True}
                )
                logger.debug("Found %s users matching email", len(users))
                if not users:
                    logger.warning("No users found for email: %s", user.email)
                    raise IdentityNotFound
                user_rep = users[0]
                logger.debug("Selected user: %s", user_rep.get("id", "Unknown"))
            elif user.phone:
                logger.debug("Searching by phone: %s", user.phone)
                user_rep = self._find_user_by_phone(user.phone)
                if not user_rep:
                    logger.warning("No users found for phone: %s", user.phone)
                    raise IdentityNotFound
                logger.debug("Selected user: %s", user_rep.get("id", "Unknown"))
            elif user.username:
                logger.debug("Searching by username: %s", user.username)
                users = self._keycloak_admin.get_users(
                    query={"username": user.username, "exact": True}
                )
                logger.debug("Found %s users matching username", len(users))
                if not users:
                    logger.warning("No users found for username: %s", user.username)
                    raise IdentityNotFound
                user_rep = users[0]
                logger.debug("Selected user: %s", user_rep.get("id", "Unknown"))
            else:
                logger.exception("No query parameters provided for user search")
                raise IdentityNotFound

        except KeycloakError as _e:
            if _e.response_code == 404:
                # Expected outcome of an existence check — e.g. FamilyService
                # probing a relationship target that may not exist. The caller
                # turns this into its own domain error, so it isn't an
                # unexpected failure: log at info, not as a red traceback.
                logger.info("User not found in Keycloak for the given query")
                raise IdentityNotFound
            logger.exception("Keycloak error getting user: %s", str(_e))
            raise

        return self._format_keycloak_user(user_rep)

    def _find_user_by_phone(self, phone: str) -> dict | None:
        """Ищет пользователя по телефону через Keycloak attribute search."""
        start_time = time.time()
        logger.info("Starting phone search for: %s", phone)

        normalized_search_phone = self._normalize_phone_for_search(phone)

        try:
            # Primary: Keycloak native attribute search. briefRepresentation=False
            # makes Keycloak return attributes inline, so we don't need a
            # follow-up get_user per candidate (avoids an N+1).
            candidates = self._keycloak_admin.get_users(
                {"q": f"phone:{normalized_search_phone}", "briefRepresentation": False}
            )
            logger.info("Attribute search returned %s candidates", len(candidates))

            for candidate in candidates:
                # Only fetch the full user if attributes are missing (older
                # Keycloak / brief fallback) — usually they're already present.
                if candidate.get("attributes"):
                    full_user = candidate
                else:
                    try:
                        full_user = self._keycloak_admin.get_user(candidate.get("id"))
                    except Exception:
                        full_user = candidate

                attrs = full_user.get("attributes") or {}
                phone_list = attrs.get("phone", [])
                if isinstance(phone_list, str):
                    phone_list = [phone_list]

                for user_phone in phone_list:
                    if self._normalize_phone_for_search(user_phone) == normalized_search_phone:
                        elapsed = time.time() - start_time
                        logger.info("Phone found via attr search! User: %s, time: %ss", full_user.get("id"), elapsed)
                        return full_user

        except Exception as e:
            logger.warning("Attribute search failed, falling back to full scan: %s", e)

        # Fallback: scan users. briefRepresentation=False returns attributes
        # inline so we don't issue a get_user per user (previously an N+1 over
        # the whole user base — a real landmine as the base grows).
        try:
            all_users = self._keycloak_admin.get_users({"briefRepresentation": False})
            logger.info("Fallback: scanning %s users from Keycloak", len(all_users))

            for user in all_users:
                if user.get("attributes"):
                    full_user = user
                else:
                    try:
                        full_user = self._keycloak_admin.get_user(user.get("id"))
                    except Exception:
                        full_user = user

                attrs = full_user.get("attributes") or {}
                phone_list = attrs.get("phone", [])
                if not phone_list:
                    continue
                if isinstance(phone_list, str):
                    phone_list = [phone_list]

                for user_phone in phone_list:
                    if not user_phone:
                        continue
                    if self._normalize_phone_for_search(user_phone) == normalized_search_phone:
                        elapsed = time.time() - start_time
                        logger.info("Phone found via full scan! User: %s, time: %ss", full_user.get("id"), elapsed)
                        return full_user

        except Exception as e:
            logger.exception("Error in full scan for phone %s: %s", phone, str(e))

        elapsed = time.time() - start_time
        logger.info("Phone not found. Search time: %ss", elapsed)
        return None

    def _format_keycloak_user(self, user_data: dict) -> KeycloakUserDTO:
        """Форматирует сырые данные Keycloak в KeycloakUserDTO"""
        if not isinstance(user_data, dict):
            try:
                user_data = dict(user_data)
            except Exception as _e:
                logger.warning("Failed to convert user_data to dict: %s", str(_e))
                pass

        attrs = user_data.get("attributes") or {}

        if not isinstance(attrs, dict):
            try:
                attrs = dict(attrs)
            except Exception as _e:
                logger.warning("Failed to convert attrs to dict: %s", str(_e))
                attrs = {}

        if "name" not in attrs or not attrs.get("name"):
            fallback = user_data.get("username") or user_data.get("email") or ""
            attrs["name"] = [fallback]
            logger.debug("Set fallback name: %s", fallback)

        user_data["attributes"] = attrs

        return KeycloakUserDTO(**user_data)

    def get_roles(self, user_id: UUID) -> list[str]:
        logger.debug("Getting roles for user: %s", user_id)
        try:
            roles = self._keycloak_admin.get_realm_roles_of_user(str(user_id))
            role_names = [role["name"] for role in roles]
            logger.debug(
                "Found %s roles for user %s: %s", len(role_names), user_id, role_names
            )
            return role_names
        except KeycloakError as _e:
            logger.exception(
                "Keycloak error getting roles for user %s: %s", user_id, str(_e)
            )
            if _e.response_code == 404:
                raise IdentityNotFound
            raise

    def get_users(self) -> list[KeycloakUserDTO]:
        """Получить всех пользователей из Keycloak."""
        return [
            self._format_keycloak_user(u) for u in self._keycloak_admin.get_users({})
        ]

    def get_user(self, user_id: str) -> KeycloakUserDTO:
        """Get user by ID (convenience method)."""
        return self.get(KeycloakUserQueryDTO(id=UUID(user_id)))

    def delete(self, user_id: UUID) -> None:
        logger.info("Deleting user: %s", user_id)
        try:
            self._keycloak_admin.delete_user(str(user_id))
            logger.info("User deleted successfully: %s", user_id)
        except KeycloakError as _e:
            logger.exception("Keycloak error deleting user %s: %s", user_id, str(_e))
            if _e.response_code == 404:
                raise IdentityNotFound
            raise

    def set_active(self, user_id: UUID, active: bool) -> None:
        logger.info("Setting user active status: user=%s, active=%s", user_id, active)
        try:
            user_before = self._keycloak_admin.get_user(str(user_id))
            logger.info("User before activation:")
            logger.info("  - Enabled: %s", user_before.get("enabled"))
            logger.info("  - Email Verified: %s", user_before.get("emailVerified"))
            logger.info("  - Required Actions: %s", user_before.get("requiredActions"))

            payload = {
                "enabled": active,
                "emailVerified": active,
                "requiredActions": [],
                "username": user_before.get("username"),
                "attributes": user_before.get("attributes") or {},
            }
            if user_before.get("email"):
                payload["email"] = user_before.get("email")

            self._keycloak_admin.update_user(
                user_id=str(user_id),
                payload=payload,
            )

            user_after = self._keycloak_admin.get_user(str(user_id))
            logger.info("User after activation:")
            logger.info("  - Enabled: %s", user_after.get("enabled"))
            logger.info("  - Email Verified: %s", user_after.get("emailVerified"))
            logger.info("  - Required Actions: %s", user_after.get("requiredActions"))

            logger.info(
                "User active status updated: user=%s, active=%s", user_id, active
            )
            self._invalidate_user_profile_cache(user_id)
        except KeycloakError as _e:
            logger.exception(
                "Keycloak error setting active status for user %s: %s", user_id, str(_e)
            )
            if _e.response_code == 404:
                raise IdentityNotFound
            raise

    def create_tokens(
        self, login: KZPhone | EmailStr, password: str
    ) -> KeycloakAccessTokenDTO:
        """
        Универсальный метод создания токенов.
        Поддерживает login как: email, телефон, username.
        """
        logger.info("Creating tokens for login: %s", login)

        username = self._resolve_username(str(login))
        logger.info("Resolved username for login '%s': %s", login, username)

        try:
            tokens = self._keycloak_openid.token(username=username, password=password)
            logger.info("Tokens created successfully for: %s", login)
            return KeycloakAccessTokenDTO(**tokens)
        except KeycloakError as exc:
            original_error = exc
            logger.exception("Keycloak error creating tokens: %s", str(original_error))

            if "Account is not fully set up" in str(original_error):
                logger.warning("Account not fully set up, waiting and retrying...")
                import time

                time.sleep(2)

                try:
                    tokens = self._keycloak_openid.token(
                        username=username, password=password
                    )
                    logger.info("Tokens created on retry for: %s", username)
                    return KeycloakAccessTokenDTO(**tokens)
                except KeycloakError as retry_exc:
                    logger.exception("Retry failed: %s", str(retry_exc))
                    raise NotVerifiedError from retry_exc

            if original_error.response_code == 401:
                raise InvalidAccessTokenError from original_error
            if original_error.response_code == 400:
                logger.warning("User not verified or other 400 error: %s", login)
                raise NotVerifiedError from original_error
            raise

    # def _get_required_action_description(self, action: str) -> str:
    #     """Возвращает описание required action"""
    #     descriptions = {
    #         "CONFIGURE_TOTP": "Настроить двухфакторную аутентификацию",
    #         "UPDATE_PASSWORD": "Обновить пароль",
    #         "UPDATE_PROFILE": "Обновить профиль",
    #         "VERIFY_EMAIL": "Подтвердить email",
    #         "UPDATE_USER_LOCALE": "Обновить язык",
    #         "terms_and_conditions": "Принять условия использования",
    #         "delete_account": "Удалить аккаунт",
    #         "update_user_attribute": "Обновить атрибуты пользователя",
    #     }
    #     return descriptions.get(action, f"Неизвестное действие: {action}")

    def refresh_tokens(self, refresh_token: str) -> KeycloakAccessTokenDTO:
        logger.info("Refreshing tokens")
        try:
            tokens = self._keycloak_openid.refresh_token(refresh_token)
            logger.info("Tokens refreshed successfully")
            return KeycloakAccessTokenDTO(**tokens)
        except KeycloakError as _e:
            logger.exception("Keycloak error refreshing tokens: %s", str(_e))
            if _e.response_code == 400:
                raise InvalidRefreshTokenError
            raise

    def set_password(self, user_id: UUID, password: str) -> bool:
        logger.info("Setting password for user: %s", user_id)
        try:
            user_before = self._keycloak_admin.get_user(str(user_id))
            logger.info("User before password set:")
            logger.info("  - Required Actions: %s", user_before.get("requiredActions"))
            logger.info("  - Email Verified: %s", user_before.get("emailVerified"))

            self._keycloak_admin.set_user_password(
                user_id=str(user_id), password=password, temporary=False
            )

            try:
                self._keycloak_admin.update_user(
                    user_id=str(user_id), payload={"requiredActions": []}
                )
                logger.info("Required actions cleared for user: %s", user_id)
            except Exception as e:
                logger.warning("Could not clear required actions: %s", str(e))

            user_after = self._keycloak_admin.get_user(str(user_id))
            logger.info("User after password set:")
            logger.info("  - Required Actions: %s", user_after.get("requiredActions"))
            logger.info("  - Email Verified: %s", user_after.get("emailVerified"))

            logger.info("Password set successfully for user: %s", user_id)
            return True
        except KeycloakError as _e:
            logger.exception(
                "Keycloak error setting password for user %s: %s", user_id, str(_e)
            )
            if _e.response_code == 404:
                raise IdentityNotFound
            raise

    def _get_realm_public_key_pem(self, force_refresh: bool = False) -> str:
        """Return the realm RSA public key as PEM, cached process-wide.

        Keycloak's `public_key()` is a network round-trip to the realm
        endpoint, so the result is cached at the class level and reused
        across requests. `force_refresh=True` refetches it (used once on a
        signature failure to survive realm key rotation).
        """
        cls = IdentityProviderClientKeycloak
        if cls._cached_public_key_pem is None or force_refresh:
            raw_key = self._keycloak_openid.public_key()
            cls._cached_public_key_pem = (
                "-----BEGIN PUBLIC KEY-----\n" f"{raw_key}\n" "-----END PUBLIC KEY-----"
            )
        return cls._cached_public_key_pem

    def get_user_sub_from_token(self, token: str) -> UUID:
        """Verify the access token locally and return its `sub`.

        Previously this called Keycloak's `/userinfo` endpoint on every
        request — a network round-trip per authenticated call. We now verify
        the JWT signature + expiry locally against the realm public key
        (cached process-wide). The `sub` claim is read straight from the
        verified payload, so no network call is needed on the hot path.

        Trade-off: local validation checks signature + expiry but not
        server-side revocation. Access tokens are short-lived (~5 min), so
        this is the standard, accepted trade-off for performance.
        """
        logger.debug("Getting user sub from token (local verify)")

        def _decode(force_refresh: bool) -> dict:
            return jwt.decode(
                token,
                self._get_realm_public_key_pem(force_refresh=force_refresh),
                algorithms=["RS256"],
                # Keycloak access tokens carry an `aud` that varies by client
                # ("account", the client id, etc.); we trust the signature and
                # don't pin audience here. Signature + expiry are enforced.
                options={"verify_aud": False},
            )

        try:
            try:
                payload = _decode(force_refresh=False)
            except ExpiredSignatureError:
                # Definitive — an expired token won't be saved by a key refresh.
                logger.warning("Access token expired")
                raise InvalidAccessTokenError
            except InvalidTokenError:
                # May be a stale cached key after realm rotation — refetch once.
                logger.info("Token verify failed, refreshing realm key and retrying")
                payload = _decode(force_refresh=True)
        except ExpiredSignatureError:
            raise InvalidAccessTokenError
        except InvalidTokenError as _e:
            logger.warning("Invalid access token: %s", str(_e))
            raise InvalidAccessTokenError

        user_sub = payload.get("sub")
        if not user_sub:
            # Some clients (notably the admin panel `tesla-admin-panel` with
            # Keycloak 26 "lightweight access tokens") issue access tokens
            # WITHOUT a `sub` claim — it is only available from /userinfo.
            # Fall back to the network call for those tokens; full tokens
            # (mobile `web-app`) keep the fast local path above.
            logger.info("Token has no 'sub' claim; falling back to /userinfo")
            try:
                user_info = self._keycloak_openid.userinfo(token)
                user_sub = user_info.get("sub")
            except KeycloakError as _e:
                logger.warning("userinfo fallback failed: %s", str(_e))
                if getattr(_e, "response_code", None) == 401:
                    raise InvalidAccessTokenError
                raise
            if not user_sub:
                logger.warning("Access token has no 'sub' even via /userinfo")
                raise InvalidAccessTokenError
        logger.debug("User sub extracted: %s", user_sub)
        return user_sub

    def logout(self, refresh_token: str) -> None:
        logger.info("Logging out user")
        try:
            self._keycloak_openid.logout(refresh_token)
            logger.info("User logged out successfully")
        except KeycloakError as _e:
            logger.exception("Keycloak error during logout: %s", str(_e))
            if _e.response_code == 400:
                raise InvalidRefreshTokenError
            raise

    def logout_all_sessions(self, user_id: UUID) -> None:
        logger.info("Revoking all sessions for user: %s", user_id)
        try:
            self._keycloak_admin.user_logout(str(user_id))
            logger.info("All sessions revoked for user: %s", user_id)
        except KeycloakError as _e:
            logger.exception("Keycloak error revoking sessions for %s: %s", user_id, str(_e))
            if _e.response_code == 404:
                raise IdentityNotFound
            raise

    def update_user(self, user_id: UUID, data: KeycloakUserUpdateDTO) -> None:
        logger.info(
            "Updating user: %s, data=%s", user_id, data.model_dump(exclude_unset=True)
        )

        try:
            current_user = self._keycloak_admin.get_user(str(user_id))

            payload = {}

            payload["username"] = current_user.get("username")

            if data.username is not None:
                payload["username"] = data.username

            if data.email is not None:
                payload["email"] = data.email

            if data.attributes is not None:
                current_attrs = current_user.get("attributes", {})
                if not isinstance(current_attrs, dict):
                    try:
                        current_attrs = dict(current_attrs)
                    except Exception:
                        current_attrs = {}

                attributes_dict = data.attributes.model_dump(exclude_unset=True)
                for key, value in attributes_dict.items():
                    if value is not None:
                        current_attrs[key] = value

                if current_attrs:
                    payload["attributes"] = current_attrs

            logger.debug("Final update payload: %s", payload)

            self._keycloak_admin.update_user(user_id=str(user_id), payload=payload)
            logger.info("User updated successfully: %s", user_id)
            self._invalidate_user_profile_cache(user_id)

        except KeycloakError as _e:
            logger.exception("Keycloak error updating user %s: %s", user_id, str(_e))
            if _e.response_code == 404:
                raise IdentityNotFound
            if _e.response_code == 409:
                error_msg = (
                    _e.error_message.decode()
                    if isinstance(_e.error_message, bytes)
                    else _e.error_message
                )
                if "email" in error_msg.lower():
                    raise EmailAlreadyExists
            raise

    # def _get_email(self, login: str) -> str:
    #     if "@" not in login:
    #         return login

    #     users = self._keycloak_admin.get_users({"email": login})
    #     if not users:
    #         logger.warning("No users found for email: %s", login)
    #         raise InvalidAccessTokenError

    #     return users[0]["username"]

    def create_oauth_tokens(self, user_id: UUID) -> KeycloakAccessTokenDTO:
        """
        Создание токенов для OAuth аутентификации.
        Использует username из Keycloak.
        """
        logger.info("Creating OAuth tokens for user: %s", user_id)
        try:
            temp_password = self._generate_oauth_password()

            self.set_password(user_id, temp_password)

            user = self.get(KeycloakUserQueryDTO(id=user_id))

            logger.info("Using username for OAuth tokens: %s", user.username)

            tokens = self._keycloak_openid.token(
                username=user.username,
                password=temp_password,
            )

            logger.info("OAuth tokens created successfully for user: %s", user_id)
            return KeycloakAccessTokenDTO(**tokens)

        except KeycloakError as e:
            logger.exception(
                "Keycloak error creating OAuth tokens for user %s: %s", user_id, str(e)
            )
            if e.response_code == 404:
                raise IdentityNotFound
            raise

    def _generate_oauth_password(self) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for i in range(32))

    def _resolve_username(self, login: str) -> str:
        """
        Универсальный метод для определения username по любому логину.
        Поддерживает: email, телефон, username.
        """
        logger.debug("Resolving username for login: %s", login)

        login = str(login).strip()

        if self._is_valid_username(login):
            logger.debug("Testing as username: %s", login)
            try:
                users = self._keycloak_admin.get_users(
                    {"username": login, "exact": True}
                )
                if users:
                    logger.debug("Found user by username: %s", login)
                    return login
            except Exception as e:
                logger.debug("Something happened: %s", e)
                pass

        if "@" in login:
            logger.debug("Treating as email: %s", login)
            try:
                return self._find_username_by_email(login)
            except InvalidAccessTokenError:
                pass

        if self._looks_like_phone(login):
            logger.debug("Treating as phone: %s", login)
            try:
                return self._find_username_by_phone(login)
            except InvalidAccessTokenError:
                pass

        logger.debug("Performing extended search for: %s", login)

        try:
            users = self._keycloak_admin.get_users(
                {"email": login.lower(), "exact": True}
            )
            if users:
                logger.debug("Found user by email (case-insensitive): %s", login)
                return users[0].get("username")
        except Exception as e:
            logger.warning("Something happened: %s", e)

        try:
            users = self._keycloak_admin.get_users({})
            for user in users:
                if user.get("username", "").lower() == login.lower():
                    logger.debug("Found user by username (case-insensitive): %s", login)
                    return user.get("username")
        except Exception as e:
            logger.debug("Something happened: %s", e)
            pass

        logger.exception("Could not resolve username for login: %s", login)
        raise InvalidAccessTokenError(f"No user found with login: {login}")

    def _is_valid_username(self, username: str) -> bool:
        """Проверяет, может ли строка быть валидным username"""
        if not username:
            return False

        if "@" in username:
            return False

        if self._looks_like_phone(username):
            return False

        return len(username) >= 3

    def _looks_like_phone(self, text: str) -> bool:
        """Проверяет, похож ли текст на телефон"""
        normalized = "".join(c for c in text if c.isdigit() or c == "+")

        if normalized.startswith("+"):
            digits = len([c for c in normalized if c.isdigit()])
            return digits >= 11  # +7 707 682 8431 = 12 цифр с +
        else:
            digits = len([c for c in normalized if c.isdigit()])
            return digits >= 10  # 77076828431 = 11 цифр без +

    def _find_username_by_email(self, email: str) -> str:
        """Находит username по email"""
        users = self._keycloak_admin.get_users({"email": email, "exact": True})
        if not users:
            logger.warning("No user found with email: %s", email)
            raise InvalidAccessTokenError(f"No user with email {email}")

        user = users[0]
        logger.debug(
            "Found user by email %s: id=%s, username=%s",
            email,
            user.get("id"),
            user.get("username"),
        )
        return user.get("username")

    def _normalize_phone_for_search(self, phone: str) -> str:
        """Нормализует телефон для поиска"""
        if not phone:
            return ""

        digits = "".join(filter(str.isdigit, phone))

        if len(digits) >= 10:
            if (
                digits.startswith("77")
                and len(digits) == 11
                or digits.startswith("87")
                and len(digits) == 11
            ):
                return "+77" + digits[2:]
            elif digits.startswith("7") and len(digits) == 11:
                return "+" + digits
            elif len(digits) == 10:
                return "+7" + digits
            elif digits.startswith("8") and len(digits) == 11:
                return "+7" + digits[1:]

        if phone.startswith("+") and (
            phone.startswith("+77")
            and len(phone) == 12
            or phone.startswith("+7")
            and len(phone) == 12
        ):
            return phone

        return phone

    # def get_user_credentials(self, user_id: UUID) -> dict:
    #     """Возвращает учетные данные пользователя для отображения на клиенте"""
    #     try:
    #         user = self.get(KeycloakUserQueryDTO(id=user_id))

    #         phone = None
    #         if (
    #             user.attributes
    #             and user.attributes.phone
    #             and len(user.attributes.phone) > 0
    #         ):
    #             phone = user.attributes.phone[0]

    #         login_methods = []
    #         if user.username:
    #             login_methods.append(user.username)
    #         if user.email:
    #             login_methods.append(user.email)
    #         if phone:
    #             login_methods.append(phone)

    #         return {
    #             "username": user.username,
    #             "email": user.email,
    #             "phone": phone,
    #             "can_login_with": login_methods,
    #         }
    #     except IdentityNotFound:
    #         raise IdentityNotFound

    def _user_exists(self, phone=None, email=None) -> bool:
        """Проверяет, существует ли пользователь с таким phone/email"""
        if phone:
            if isinstance(phone, list):
                for ph in phone:
                    try:
                        self.get(KeycloakUserQueryDTO(phone=ph))
                        return True
                    except IdentityNotFound:
                        continue
            else:
                try:
                    self.get(KeycloakUserQueryDTO(phone=phone))
                    return True
                except IdentityNotFound:
                    pass

        if email:
            try:
                self.get(KeycloakUserQueryDTO(email=email))
                return True
            except IdentityNotFound:
                pass

        return False

    # def clear_required_actions(self, user_id: UUID) -> None:
    #     """Очищает все required actions для пользователя"""
    #     logger.info("Clearing required actions for user: %s", user_id)
    #     try:
    #         self._keycloak_admin.update_user(str(user_id), {"requiredActions": []})
    #         logger.info("Required actions cleared for user: %s", user_id)
    #     except Exception as e:
    #         logger.exception("Failed to clear required actions: %s", str(e))
    #         raise

    # def get_required_actions(self, user_id: UUID) -> list[str]:
    #     """Получить все required actions пользователя"""
    #     logger.info("Getting required actions for user: %s", user_id)
    #     try:
    #         user = self._keycloak_admin.get_user(str(user_id))
    #         required_actions = user.get("requiredActions", [])
    #         logger.info("Required actions for user %s: %s", user_id, required_actions)
    #         return required_actions
    #     except Exception as e:
    #         logger.exception("Error getting required actions: %s", str(e))
    #         return []

    # def force_clear_all_requirements(self, user_id: UUID) -> None:
    #     """Принудительно очистить все требования и верифицировать всё"""
    #     logger.info("Force clearing all requirements for user: %s", user_id)

    #     try:
    #         user = self._keycloak_admin.get_user(str(user_id))

    #         logger.info("User before cleanup:")
    #         logger.info("  - enabled: %s", user.get("enabled"))
    #         logger.info("  - emailVerified: %s", user.get("emailVerified"))
    #         logger.info("  - requiredActions: %s", user.get("requiredActions"))
    #         logger.info("  - attributes: %s", user.get("attributes"))

    #         attrs = user.get("attributes", {})

    #         if "phone" in attrs and attrs["phone"] and "phoneVerified" not in attrs:
    #             attrs["phoneVerified"] = ["true"]
    #             logger.info(
    #                 "Added phoneVerified attribute for phone: %s", attrs["phone"]
    #             )

    #         payload = {"enabled": True, "emailVerified": True, "requiredActions": []}

    #         for field in ["username", "email", "firstName", "lastName", "attributes"]:
    #             if field in user and user[field] is not None:
    #                 payload[field] = user[field] if field != "attributes" else attrs

    #         logger.info("Update payload: %s", payload)

    #         self._keycloak_admin.update_user(str(user_id), payload)

    #         import time

    #         time.sleep(0.5)

    #         updated_user = self._keycloak_admin.get_user(str(user_id))
    #         logger.info("User after cleanup:")
    #         logger.info("  - enabled: %s", updated_user.get("enabled"))
    #         logger.info("  - emailVerified: %s", updated_user.get("emailVerified"))
    #         logger.info("  - requiredActions: %s", updated_user.get("requiredActions"))

    #         logger.info("Successfully cleared all requirements for user: %s", user_id)

    #     except Exception as e:
    #         logger.exception("Error force clearing requirements: %s", str(e))
    #         raise

    def update_user_subscription(
        self,
        user_id: UUID,
        plan: PlanType,
        expires_at: datetime | None = None,
        subscription_cancelled: bool | None = None,
    ) -> None:
        """
        Обновить подписку пользователя в Keycloak
        """
        logger.info(
            "Updating user subscription in Keycloak: user_id=%s, plan=%s, expires_at=%s",
            user_id,
            plan.value,
            expires_at,
        )

        try:
            user = self._keycloak_admin.get_user(str(user_id))
            if not user:
                raise IdentityNotFound(f"User {user_id} not found")

            attrs = user.get("attributes", {})
            if not isinstance(attrs, dict):
                try:
                    attrs = dict(attrs)
                except Exception as e:
                    logger.warning("Failed to convert attrs to dict: %s", str(e))
                    attrs = {}

            attrs["plan"] = [plan.value]
            if expires_at:
                attrs["subscription_end"] = [expires_at.isoformat()]
            else:
                attrs.pop("subscription_end", None)

            if subscription_cancelled is not None:
                attrs["subscription_cancelled"] = [str(subscription_cancelled).lower()]

            payload = {"username": user.get("username"), "attributes": attrs}

            if user.get("email"):
                payload["email"] = user.get("email")

            self._keycloak_admin.update_user(str(user_id), payload)

            logger.info("User subscription updated successfully: %s", user_id)
            self._invalidate_user_profile_cache(user_id)

        except KeycloakError as e:
            logger.exception("Keycloak error updating user subscription: %s", e)
            if e.response_code == 404:
                raise IdentityNotFound(f"User {user_id} not found")
            raise
        except Exception as e:
            logger.exception("Unexpected error updating user subscription: %s", e)
            raise

    # def _username_exists(self, username: str) -> bool:
    #     """Проверяет, существует ли username"""
    #     try:
    #         users = self._keycloak_admin.get_users(
    #             {"username": username, "exact": True}
    #         )
    #         return len(users) > 0
    #     except Exception as e:
    #         logger.warning("Error checking username existence: %s", e)
    #         return False

    # def _find_username_by_any_field(self, identifier: str) -> str | None:
    #     """Ищет username по любому полю (email, phone, username)"""
    #     if "@" in identifier:
    #         try:
    #             return self._find_username_by_email(identifier)
    #         except InvalidAccessTokenError:
    #             pass

    #     try:
    #         return self._find_username_by_phone(identifier)
    #     except InvalidAccessTokenError:
    #         pass

    #     if self._username_exists(identifier):
    #         return identifier

    #     try:
    #         users = self._keycloak_admin.get_users({"username": identifier})
    #         if users:
    #             return users[0].get("username")
    #     except Exception as e:
    #         logger.debug("Search by username failed: %s", e)

    #     return None

    def _find_username_by_phone(self, phone: str) -> str:
        """Находит username по телефону"""
        logger.debug("Finding username by phone: %s", phone)

        user = self._find_user_by_phone(phone)
        if not user:
            logger.warning("No user found with phone: %s", phone)
            raise InvalidAccessTokenError(f"No user with phone {phone}")

        username = user.get("username")
        if not username:
            logger.exception("User found by phone but no username: %s", phone)
            raise InvalidAccessTokenError("User has no username")

        logger.debug("Found username by phone %s: %s", phone, username)
        return username

    # def find_user_by_login(self, login: str) -> KeycloakUserDTO | None:
    #     """
    #     Универсальный поиск пользователя по любому логину.
    #     Возвращает пользователя или None.
    #     """
    #     try:
    #         if "@" in login:
    #             return self.get(KeycloakUserQueryDTO(email=login))
    #     except IdentityNotFound:
    #         pass

    #     try:
    #         if self._looks_like_phone(login):
    #             user_data = self._find_user_by_phone(login)
    #             if user_data:
    #                 return self._format_keycloak_user(user_data)
    #     except Exception as e:
    #         logger.debug("Something happened: %s", e)
    #         pass

    #     try:
    #         users = self._keycloak_admin.get_users({"username": login, "exact": True})
    #         if users:
    #             return self._format_keycloak_user(users[0])
    #     except Exception as e:
    #         logger.debug("Something happened: %s", e)
    #         pass

    #     return None

    def add_realm_role(self, user_id: UUID, role_name: str) -> None:
        """Добавить роль пользователю."""
        try:
            logger.info("Adding role %s to user %s", role_name, user_id)
            role = self._keycloak_admin.get_realm_role(role_name)
            logger.debug("Found roles: %s", role)
            if not role:
                raise ValueError(f"Role {role_name} not found")
            role_id = role["id"]
            logger.debug("Found role id: %s", role_id)
            self._keycloak_admin.assign_realm_roles(
                str(user_id), [{"id": role_id, "name": role_name}]
            )
            logger.info("Added role %s to user %s", role_name, user_id)
        except Exception as e:
            logger.exception(
                "Failed to add role %s to user %s: %s", role_name, user_id, e
            )
            raise
