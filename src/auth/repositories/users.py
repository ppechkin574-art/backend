import logging
from typing import Protocol
from uuid import UUID

from pydantic import EmailStr

from auth.converters import (
    to_keycloak_create_user_dto,
    to_keycloak_user_query_dto,
    to_keycloak_user_update_dto,
    to_user_dto,
    to_user_query_dto,
    to_user_tokens_dto,
)
from auth.dtos import UserCreateDTO, UserDTO, UserQueryDTO
from auth.dtos.users import UserTokensDTO, UserUpdateDTO
from auth.exceptions import (
    UserBadCredentialsError,
    UserEmailExistsError,
    UserExistsError,
    UserInvalidAccessTokenError,
    UserInvalidRefreshTokenError,
    UserNotFoundError,
    UserNotVerifiedError,
)
from clients import IdentityProviderClientInterface
from clients.identity_provider import IdentityNotFound, InvalidAccessTokenError
from clients.identity_provider.exceptions import (
    EmailAlreadyExists,
    InvalidRefreshTokenError,
    NotVerifiedError,
)
from utils.cache import CacheService, CacheStrategy
from utils.validators import KZPhone

logger = logging.getLogger(__name__)


class UserRepositoryInterface(Protocol):
    def create(self, user: UserCreateDTO) -> UserDTO:
        """
        Create user.

        Args:
            user: User Create DTO.

        Returns:
            UserDTO: Created user information.

        Raises:
            UserExistsError: User with such phone already exists.
        """
        raise NotImplementedError

    def get(self, user: UserQueryDTO) -> UserDTO:
        """
        Get User.

        Args:
            user: Parameters to query user.

        Returns:
            UserDTO: Found user information.

        Raises:
            UserNotFoundError: User not found.
        """
        raise NotImplementedError

    def delete(self, user_id: UUID) -> None:
        """
        Delete user.

        Args:
            user_id: ID of the user to delete.

        Raises:
            UserNotFoundError: User not found.
        """
        raise NotImplementedError

    def set_active(self, user_id: UUID, active: bool) -> None:
        """
        Change active state of the user.

        Args:
            user_id: ID of the user to change active state to.
            active: Value to which active state will bi set.

        Raises:
            UserNotFoundError: User not found.
        """
        raise NotImplementedError

    def create_tokens(self, login: str, password: str) -> UserTokensDTO:
        """
        Create tokens for the user.

        Args:
            login: phone or email
            password: password

        Returns:
            UserTokensDTO: Tokens for the user.

        Raises:
            UserBadCredentialsError: When credentials don't match with any user.
        """
        raise NotImplementedError

    def refresh_token(self, refresh_token: str) -> UserTokensDTO:
        """
        Refresh tokens for the user.

        Args:
            refresh_token: refresh_token

        Returns:
            UserTokensDTO: Tokens for the user.

        Raises:
            UserInvalidRefreshTokenError: When credentials are bad.
        """
        raise NotImplementedError

    def change_password(self, user_id: UUID, password: str) -> None:
        """
        Change user password.

        Args:
            user_id: user_id
            password: password

        Raises:
            UserNotFoundError: When user_id not found.
        """
        raise NotImplementedError

    def get_user_from_token(self, access_token: str) -> UserDTO:
        """
        Gets user by token.

        Args:
            access_token: access_token

        Returns:
            UserDTO: User information.

        Raises:
            UserNotFoundError
            UserInvalidTokenError: When by access_token not found.
        """
        raise NotImplementedError

    def logout(self, refresh_token: str) -> None:
        """
        Logout user.

        Args:
            refresh_token: Refresh token.

        Raises:
            UserInvalidRefreshTokenError: invalid refresh token.
        """
        raise NotImplementedError

    def update(self, user: UserDTO, data: UserUpdateDTO) -> None:
        """
        Updates user by user_id.

        Args:
            user: UserDTO
            data: UpdateUserDTO

        Raises:
            UserNotFoundError: When user by user.id not found.
            UserEmailExistsError: When email of user exists.
        """
        raise NotImplementedError

    def create_oauth_tokens(self, email: str) -> UserTokensDTO:
        """
        Create tokens for OAuth authentication (without password).

        Args:
            email: User email

        Returns:
            UserTokensDTO: Session tokens.

        Raises:
            UserNotFoundError: If user not found.
            UserNotVerifiedError: If user not verified.
        """
        raise NotImplementedError


class UserRepositoryKeycloak:
    # Short TTL for the cached profile. Writes that go through
    # IdentityProviderClientKeycloak (update_user / update_user_subscription /
    # set_active) invalidate the key immediately, so this TTL only bounds
    # staleness for any change that bypasses the client.
    _PROFILE_CACHE_TTL = 60

    def __init__(
        self,
        identity_provider_client: IdentityProviderClientInterface,
        cache_service: CacheService | None = None,
    ):
        self.identity_provider_client = identity_provider_client
        self._cache = cache_service

    def create(self, user: UserCreateDTO) -> UserDTO:
        kc_dto = to_keycloak_create_user_dto(user)
        keycloak_user, is_created = self.identity_provider_client.get_or_create(kc_dto)
        roles = self.identity_provider_client.get_roles(keycloak_user.id)
        _user = to_user_dto(keycloak_user, roles)
        if not is_created:
            # If phone-only user was found by synthetic email but has no phone attribute,
            # it's a zombie from a previous failed registration — delete and recreate.
            if user.phone and not _user.phone:
                logger.info(
                    "Zombie user detected (no phone attr on %s), deleting and retrying",
                    _user.id,
                )
                self.identity_provider_client.delete(_user.id)
                keycloak_user, is_created = self.identity_provider_client.get_or_create(kc_dto)
                roles = self.identity_provider_client.get_roles(keycloak_user.id)
                _user = to_user_dto(keycloak_user, roles)
                if not is_created:
                    raise UserExistsError(is_active=_user.is_active, user_id=_user.id)
            else:
                raise UserExistsError(is_active=_user.is_active, user_id=_user.id)
        return _user

    def get(self, user: UserQueryDTO) -> UserDTO:
        try:
            keycloak_user = self.identity_provider_client.get(to_keycloak_user_query_dto(user))
            roles = self.identity_provider_client.get_roles(keycloak_user.id)
            return to_user_dto(keycloak_user, roles)
        except IdentityNotFound:
            raise UserNotFoundError

    def delete(self, user_id: UUID) -> None:
        try:
            self.identity_provider_client.delete(user_id)
        except IdentityNotFound:
            raise UserNotFoundError

    def set_active(self, user_id: UUID, active: bool) -> None:
        try:
            self.identity_provider_client.set_active(user_id, active)
        except IdentityNotFound:
            raise UserNotFoundError

    def create_tokens(self, login: KZPhone | EmailStr, password: str) -> UserTokensDTO:
        try:
            keycloak_tokens = self.identity_provider_client.create_tokens(login, password)
            return to_user_tokens_dto(keycloak_tokens)
        except InvalidAccessTokenError:
            raise UserBadCredentialsError
        except NotVerifiedError:
            raise UserNotVerifiedError

    def refresh_token(self, refresh_token: str) -> UserTokensDTO:
        try:
            return to_user_tokens_dto(self.identity_provider_client.refresh_tokens(refresh_token))
        except InvalidRefreshTokenError:
            raise UserInvalidRefreshTokenError

    def change_password(self, user_id: UUID, password: str) -> None:
        try:
            self.identity_provider_client.set_password(user_id, password)
        except IdentityNotFound:
            raise UserNotFoundError

    def get_user_from_token(self, access_token: str) -> UserDTO:
        try:
            keycloak_user_sub = self.identity_provider_client.get_user_sub_from_token(access_token)

            def _fetch() -> UserDTO:
                # The two Keycloak network round-trips (get user + get roles)
                # live here so they only run on a cache miss.
                user_query = to_user_query_dto(user_id=keycloak_user_sub)
                try:
                    user = self.identity_provider_client.get(
                        to_keycloak_user_query_dto(user_query)
                    )
                    roles = self.identity_provider_client.get_roles(user.id)
                    return to_user_dto(user, roles)
                except IdentityNotFound:
                    raise UserNotFoundError

            if self._cache is None:
                return _fetch()

            # Cache the resolved profile by sub. Keyed identically to the
            # invalidation in IdentityProviderClientKeycloak's write methods.
            key = self._cache.make_key(
                CacheStrategy.USER, user_id=keycloak_user_sub, resource="profile"
            )
            return self._cache.get_or_set(
                key, _fetch, ttl=self._PROFILE_CACHE_TTL, return_type=UserDTO
            )
        except InvalidAccessTokenError:
            raise UserInvalidAccessTokenError

    def logout(self, refresh_token: str) -> None:
        try:
            return self.identity_provider_client.logout(refresh_token)
        except InvalidRefreshTokenError:
            raise UserInvalidRefreshTokenError

    def update(self, user: UserDTO, data: UserUpdateDTO) -> None:
        try:
            self.identity_provider_client.update_user(user.id, to_keycloak_user_update_dto(user, data))
        except IdentityNotFound:
            raise UserNotFoundError
        except EmailAlreadyExists:
            raise UserEmailExistsError

    def create_oauth_tokens(self, email: str) -> UserTokensDTO:
        logger.info("Creating OAuth tokens for: %s", email)
        try:
            user = self.get(UserQueryDTO(email=email))

            if not user.is_active:
                logger.warning("OAuth login attempt for inactive user: %s", email)
                raise UserNotVerifiedError

            tokens = to_user_tokens_dto(self.identity_provider_client.create_oauth_tokens(user.id))

            logger.info("OAuth tokens created successfully for: %s", email)
            return tokens

        except IdentityNotFound:
            logger.warning("User not found for OAuth login: %s", email)
            raise UserNotFoundError
