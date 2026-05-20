import contextlib
import logging
import os
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from auth.converters import (
    to_auth_session_dto,
    to_user_create_dto,
    to_user_dto,
    to_user_query_dto,
)
from auth.dtos import (
    AuthLoginDTO,
    AuthRegisterDTO,
    AuthSessionDTO,
    ConfirmationCodeAction,
    UserDTO,
)
from auth.dtos.auth import OAuthProviders
from auth.dtos.confirmation_codes import (
    ConfirmationCodeCreateDTO,
    ConfirmationCodeQueryDTO,
)
from auth.dtos.users import UserUpdateDTO
from auth.exceptions import (
    AuthAccessInvalidTokenError,
    AuthBadCredentialsError,
    AuthConfirmationCodeExpiredError,
    AuthFailedConfirmationError,
    AuthInvalidConfirmationCodeError,
    AuthInvalidRefreshTokenError,
    AuthNotVerifiedError,
    AuthUserEmailExistsError,
    AuthUserExistsError,
    AuthUserNotFoundError,
    AuthUserPhoneExistsError,
    ConfirmationCodeExistsError,
    ConfirmationCodeNotFoundError,
    UserBadCredentialsError,
    UserEmailExistsError,
    UserExistsError,
    UserInvalidAccessTokenError,
    UserInvalidRefreshTokenError,
    UserNotFoundError,
    UserNotVerifiedError,
    UserPhoneExistsError,
)
from auth.oauth_helper import OAuthHelper
from auth.repositories import (
    ConfirmationCodeRepositoryInterface,
    UserRepositoryInterface,
)
from clients import NotificationClientInterface, NotificationMessageDTO
from clients.apple.client import AppleOAuthClient
from clients.google.client import GoogleOAuthClient
from clients.identity_provider.client import IdentityProviderClientKeycloak
from clients.identity_provider.dtos import KeycloakUserQueryDTO
from clients.identity_provider.exceptions import IdentityNotFound
from clients.notification import CodePlatform
from common.enums import PlanType
from utils.file_service import FileService

logger = logging.getLogger(__name__)


def is_rate_limit_bypassed(contact: str | None) -> bool:
    """True iff this contact is on the rate-limit bypass list — both the
    App Store reviewer phone(s) (REVIEWER_TEST_PHONE, comma-separated)
    and dev test numbers (DEV_RATE_LIMIT_BYPASS_PHONES, comma-separated)
    qualify.

    Duplicated here instead of imported from `api.middlewares.rate_limit`
    to avoid an `auth → api` cycle (the API layer already imports from
    auth heavily). Same pattern `sms_quota.py::_is_reviewer_test_contact`
    follows. Logic is trivial enough that drift risk is low; if it grows
    move both copies into a shared `common` helper.
    """
    if not contact:
        return False
    for env_name in ("REVIEWER_TEST_PHONE", "DEV_RATE_LIMIT_BYPASS_PHONES"):
        raw = os.getenv(env_name)
        if not raw:
            continue
        for entry in raw.split(","):
            if entry.strip() == contact:
                return True
    return False


def _mask_contact(contact: str) -> str:
    """Return a partial mask of a contact for safe logging / dev-channel
    alerts. Keeps the country prefix and the last 4 chars so support can
    correlate complaints, but hides the bulk of the identifier.
    Examples: '+77787943760' → '+7778***3760', 'user@aima.kz' → 'us***@aima.kz'.
    """
    if not contact:
        return "?"
    if "@" in contact:
        local, _, domain = contact.partition("@")
        head = local[:2] if len(local) > 2 else local
        return f"{head}***@{domain}"
    if len(contact) <= 8:
        return f"{contact[:3]}***"
    return f"{contact[:5]}***{contact[-4:]}"


class AuthServiceInterface(Protocol):
    """Authentication and user management service interface."""

    def request_code(self, contact: str, platform: CodePlatform, action: ConfirmationCodeAction) -> UUID:
        """Request a confirmation code for various actions.

        Args:
            contact: Email or phone number
            platform: Platform to send the code (EMAIL, SMS, WHATSAPP, etc.)
            action: Action type (REGISTER, RESET_PASSWORD, CHANGE_EMAIL, etc.)

        Returns:
            UUID: Verification ID for the code

        Raises:
            ValueError: Invalid contact format
            AuthUserExistsError: User already exists for registration
        """
        raise NotImplementedError

    def check_code(self, verification_id: UUID, code: int, action: ConfirmationCodeAction) -> bool:
        """Verify a confirmation code.

        Args:
            verification_id: Code verification ID
            code: Confirmation code to check
            action: Action type

        Returns:
            bool: True if code is valid and verified
        """
        raise NotImplementedError

    def complete_registration(self, verification_id: UUID, password: str, name: str) -> AuthSessionDTO:
        """Complete user registration after code verification.

        Args:
            verification_id: Verified code ID
            password: User password
            name: User display name

        Returns:
            AuthSessionDTO: Authentication tokens and user data

        Raises:
            AuthInvalidConfirmationCodeError: Invalid or unverified code
            AuthUserExistsError: User already exists
            AuthFailedConfirmationError: Registration failed
        """
        raise NotImplementedError

    def complete_password_reset(
        self, verification_id: UUID, new_password: str
    ) -> AuthSessionDTO:
        """Complete password reset after code verification.

        Side effects: revokes every existing session for the user (so a
        compromised device loses access on next request) and mints a fresh
        token pair so the caller can log the user straight back in without
        a separate /login round-trip.

        Args:
            verification_id: Verified code ID
            new_password: New password to set

        Returns:
            AuthSessionDTO: Fresh access + refresh tokens

        Raises:
            AuthInvalidConfirmationCodeError: Invalid or unverified code
            AuthUserNotFoundError: User not found
            AuthFailedConfirmationError: Password reset failed
        """
        raise NotImplementedError

    def login(self, params: AuthLoginDTO) -> AuthSessionDTO:
        """Authenticate user with credentials.

        Args:
            params: Login credentials (login/password)

        Returns:
            AuthSessionDTO: Authentication tokens

        Raises:
            AuthBadCredentialsError: Invalid credentials
            AuthNotVerifiedError: User not verified
        """
        raise NotImplementedError

    def refresh_token(self, refresh_token: str) -> AuthSessionDTO:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            AuthSessionDTO: New authentication tokens

        Raises:
            AuthInvalidRefreshTokenError: Invalid refresh token
        """
        raise NotImplementedError

    def logout(self, refresh_token: str) -> None:
        """Invalidate refresh token (logout).

        Args:
            refresh_token: Refresh token to invalidate

        Raises:
            AuthInvalidRefreshTokenError: Invalid refresh token
        """
        raise NotImplementedError

    def get_user_from_token(self, access_token: str) -> UserDTO:
        """Get user from access token.

        Args:
            access_token: Valid access token

        Returns:
            UserDTO: User data

        Raises:
            AuthAccessInvalidTokenError: Invalid access token
        """
        raise NotImplementedError

    def update_user_profile(
        self,
        user: UserDTO,
        data: UserUpdateDTO,
        # file_service: Optional[FileService] = None,
    ) -> UserDTO:
        """Update user profile information.

        Args:
            user: Current user
            data: Updated user data
            file_service: Optional file service for avatar handling

        Returns:
            UserDTO: Updated user data

        Raises:
            AuthUserNotFoundError: User not found
            AuthUserEmailExistsError: Email already in use
            AuthUserPhoneExistsError: Phone already in use
        """
        raise NotImplementedError

    def delete_account(self, user: UserDTO, file_service: FileService | None = None) -> None:
        """Delete user account.

        Args:
            user: User to delete
            file_service: Optional file service for avatar cleanup

        Raises:
            AuthUserNotFoundError: User not found
        """
        raise NotImplementedError

    def change_password(self, user_id: UUID, old_password: str, new_password: str) -> None:
        """Change user password.

        Args:
            user_id: User ID
            old_password: Current password
            new_password: New password

        Raises:
            AuthBadCredentialsError: Invalid current password
            AuthUserNotFoundError: User not found
        """
        raise NotImplementedError

    def change_contact_request(self, user_id: UUID, contact: str, platform: CodePlatform) -> UUID:
        """Request verification code for contact change (email or phone).

        Args:
            user_id: User ID
            contact: New contact (email or phone)
            platform: Platform to send verification code

        Returns:
            UUID: Verification ID

        Raises:
            ValueError: Invalid contact format
            AuthUserEmailExistsError: Email already in use by another user
            AuthUserPhoneExistsError: Phone already in use by another user
        """
        raise NotImplementedError

    def change_contact_confirm(self, verification_id: UUID, code: int) -> UserDTO:
        """Confirm contact change with verification code.

        Args:
            verification_id: Verification ID from change_contact_request
            code: Verification code

        Returns:
            UserDTO: Updated user data

        Raises:
            AuthInvalidConfirmationCodeError: Invalid or expired code
            AuthUserEmailExistsError: Email now in use by another user
            AuthUserPhoneExistsError: Phone now in use by another user
        """
        raise NotImplementedError

    def login_via_oauth(self, code: str, provider: OAuthProviders) -> AuthSessionDTO:
        """Authenticate user via OAuth provider.

        Args:
            code: OAuth authorization code
            provider: OAuth provider (GOOGLE, APPLE)

        Returns:
            AuthSessionDTO: Authentication tokens

        Raises:
            ValueError: Invalid authorization code or token
        """
        raise NotImplementedError

    def is_admin(self, user: UserDTO) -> bool:
        """Check if user has admin role.

        Args:
            user: User to check

        Returns:
            bool: True if user has admin role
        """
        raise NotImplementedError

    def check_subscription_status(self, user: UserDTO) -> dict:
        """Check user's subscription status and auto-downgrade if expired.

        Args:
            user: User to check

        Returns:
            dict: Subscription status with plan, expiration, and active status
        """
        raise NotImplementedError

    def has_access(self, user: UserDTO, required_plan: PlanType | None = None) -> bool:
        """Check if user has access to content based on subscription.

        Args:
            user: User to check
            required_plan: Optional required plan type

        Returns:
            bool: True if user has access
        """
        raise NotImplementedError

    def update_user_plan(self, user: UserDTO, plan: PlanType, duration_days: int) -> UserDTO:
        """Update user's subscription plan.

        Args:
            user: User to update
            plan: New plan type
            duration_days: Subscription duration in days

        Returns:
            UserDTO: Updated user data
        """
        raise NotImplementedError

    def activate_free_trial(self, user: UserDTO) -> UserDTO:
        """Activate free trial for user (3 days).

        Args:
            user: User to activate trial for

        Returns:
            UserDTO: Updated user data
        """
        raise NotImplementedError

    # def activate_lite_subscription(self, user: UserDTO) -> UserDTO:
    #     """Activate Lite subscription for 30 days.

    #     Args:
    #         user: User to activate subscription for

    #     Returns:
    #         UserDTO: Updated user data
    #     """
    #     raise NotImplementedError


class AuthService:
    def __init__(
        self,
        users: UserRepositoryInterface,
        confirmation_codes: ConfirmationCodeRepositoryInterface,
        notification_client: NotificationClientInterface,
        email_client: NotificationClientInterface,
        sms_client: NotificationClientInterface,
        whatsapp_client: NotificationClientInterface,
        google_client: GoogleOAuthClient,
        apple_client: AppleOAuthClient,
        oauth_helper: OAuthHelper,
        identity_provider: IdentityProviderClientKeycloak,
    ):
        self._users = users
        self._confirmation_codes = confirmation_codes
        self._notification_client = notification_client
        self._email_client = email_client
        self._sms_client = sms_client
        self._whatsapp_client = whatsapp_client
        self.google_client = google_client
        self.apple_client = apple_client
        self.oauth_helper = oauth_helper
        self.identity_provider = identity_provider

        self.CODE_EXPIRATION_SECONDS = 10 * 60
        self.MAX_ATTEMPTS = 3

    def request_code(self, contact: str, platform: CodePlatform, action: ConfirmationCodeAction) -> UUID:
        logger.info(
            "Request for %s confirmation code to contact %s via %s",
            action,
            contact,
            platform,
        )

        if action == ConfirmationCodeAction.REGISTER:
            if "@" in contact:
                email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
                if not re.match(email_pattern, contact):
                    raise ValueError(
                        "Invalid email format: must be a valid email address with name, '@' symbol, and domain"
                    )
            else:
                phone_pattern = r"^\+77\d{9}$"
                if not re.match(phone_pattern, contact):
                    raise ValueError("Phone must be a valid Kazakhstan mobile number (+77XXXXXXXXX)")

        if action == ConfirmationCodeAction.CHANGE_PHONE:
            phone_pattern = r"^\+77\d{9}$"
            if not re.match(phone_pattern, contact):
                raise ValueError("Phone must be a valid Kazakhstan mobile number (+77XXXXXXXXX)")

        if action == ConfirmationCodeAction.CHANGE_EMAIL and "@" not in contact:
            raise ValueError("Invalid email format: must be a valid email address with name, '@' symbol, and domain")

        contact = self._normalize_contact(contact)

        # App Store / Play Store reviewer bypass: a single reserved phone
        # number bypasses the SMS gateway and uses a hardcoded confirmation
        # code. Without this, reviewers in Cupertino can never receive an
        # SMS through SMSC.kz and the app gets rejected for «not functional».
        # The bypass:
        #   * skips the SMSC.kz call entirely (no budget drain)
        #   * stores a fixed code in Redis like a normal request, so the
        #     existing check_code path validates without any extra branches
        #   * skips the «user already exists» guard so the reviewer can
        #     re-run the whole sign-up flow on every fresh review
        # Risk: if the reserved number leaks publicly, attackers can register
        # a single throwaway account. They get the same 3-day trial as any
        # new user — no admin escalation. Mitigation: pick a phone shape no
        # real Kazakhstan operator hands out (default +77001234567).
        is_reviewer_test_contact = self._is_reviewer_test_contact(contact)
        is_rate_limit_bypass = is_rate_limit_bypassed(contact)

        # Per-contact rate limit. block_key is set with TTL in _set_resend_block
        # only after a successful primary-channel send (Q4=A: don't penalise the
        # user when SMSC/email itself fails — they should be able to retry).
        # The endpoint-level slowapi limit ("1/minute" per IP) is the first
        # gate; this Redis key is the second gate per phone/email so an attacker
        # rotating IPs can't burn through SMSC budget against a single number.
        #
        # Bypass contacts (REVIEWER_TEST_PHONE + DEV_RATE_LIMIT_BYPASS_PHONES)
        # skip this gate too, otherwise the dev who put their number in the
        # bypass list would still wait 60 sec between test requests.
        block_key = f"block:contact:{contact}"
        ttl_remaining = (
            0 if is_rate_limit_bypass
            else self._confirmation_codes._redis.ttl(block_key)
        )
        if ttl_remaining > 0:
            raise AuthInvalidConfirmationCodeError(
                f"Слишком частые запросы. Попробуй через {ttl_remaining} сек."
            )

        verification_id = uuid.uuid4()
        user_id = verification_id

        additional_data = {}

        if action == ConfirmationCodeAction.RESET_PASSWORD:
            user = self._get_user_by_contact(contact)
            if not user:
                logger.warning("User not found for password reset: %s", contact)
                raise AuthUserNotFoundError("User with %s not found", contact)
            additional_data["real_user_id"] = str(user.id)

        elif action == ConfirmationCodeAction.REGISTER:
            is_phone = "@" not in contact
            # Reviewer bypass: skip the «exists» check so Apple can re-run
            # registration repeatedly across resubmissions without us having
            # to manually delete the test user in Keycloak.
            if is_phone and not is_reviewer_test_contact:
                logger.info("Checking if phone %s is already registered", contact)
                try:
                    user_query = to_user_query_dto(phone=contact)
                    existing_user = self._users.get(user_query)
                    logger.warning(
                        "User with phone %s already exists. User ID: %s",
                        contact,
                        existing_user.id,
                    )
                    raise AuthUserExistsError("User with phone %s already exists", contact)
                except UserNotFoundError:
                    logger.info("User with phone %s not found, can register", contact)
                except AuthUserExistsError:
                    raise
                except Exception as e:
                    logger.exception(
                        "Error checking if user with phone %s exists: %s",
                        contact,
                        e,
                    )

        elif action == ConfirmationCodeAction.CHANGE_EMAIL:
            pass

        # Reviewer bypass: fixed code from env so it's documented in App
        # Store Connect's «Sign-In Required» field and stays constant
        # between resubmissions. Default 123456 if env not set, matches
        # the canonical App Review playbook for phone-auth apps.
        if is_reviewer_test_contact:
            code = int(os.getenv("REVIEWER_TEST_CODE", "123456"))
        else:
            code = secrets.choice(range(100000, 999999))

        confirmation_code_dto = ConfirmationCodeCreateDTO(
            registration_id=verification_id,
            contact=contact,
            user_id=user_id,
            code=code,
            expiration=self.CODE_EXPIRATION_SECONDS,
            action=action,
            is_temporary=True,
        )

        try:
            self._confirmation_codes.create(confirmation_code_dto)

            if additional_data:
                redis = self._confirmation_codes._redis
                index_key = f"index:temp_reg_id:{verification_id}"
                code_ids = redis.smembers(index_key)
                if code_ids:
                    code_id = next(iter(code_ids)).decode()
                    for key, value in additional_data.items():
                        redis.hset(code_id, key, value)
                    logger.info("Saved additional data: %s", additional_data)

        except ConfirmationCodeExistsError as e:
            logger.info("Duplicate code request, regenerating code for %s", contact)
            with contextlib.suppress(ConfirmationCodeNotFoundError):
                self._confirmation_codes.delete(e.confirmation_code_id)
            self._confirmation_codes.create(confirmation_code_dto)

        # Reviewer bypass: don't actually call SMSC for the reserved phone —
        # the code is already in Redis (line above), check_code will accept
        # it. Saves SMS budget and avoids the inevitable «can't deliver»
        # error from SMSC for a fake number.
        if is_reviewer_test_contact:
            logger.info("Reviewer bypass: skipping SMS send for %s", contact)
            sent_ok = True
        else:
            sent_ok = self._send_confirmation_code(contact, code, platform)

        # Q4=A: only block on a real successful send. If SMS failed and we fell
        # back to dev channel, the user got nothing — let them retry without
        # waiting 60s. Q2=C: even on failure we keep the verification_id and
        # return it (so a later successful retry hits the same Redis entry).
        # Bypass contacts skip the block entirely (the gate above already
        # short-circuits to ttl=0; this keeps the Redis state clean too).
        if sent_ok and not is_rate_limit_bypass:
            self._confirmation_codes._redis.setex(block_key, 60, "1")

        logger.info(
            "Code %s requested for contact: %s, verification_id: %s, sent_ok: %s",
            action,
            contact,
            verification_id,
            sent_ok,
        )
        return verification_id

    def check_code(self, verification_id: UUID, code: int, action: ConfirmationCodeAction) -> bool:
        logger.info("Checking code %s for verification_id: %s", action, verification_id)

        try:
            query = ConfirmationCodeQueryDTO(
                registration_id=verification_id,
                code=code,
                action=action,
                is_temporary=True,
            )

            confirmation_code = self._confirmation_codes.get(query)

            if confirmation_code.expires_at and confirmation_code.expires_at < datetime.now(UTC):
                logger.warning("Code expired for verification_id: %s", verification_id)
                with contextlib.suppress(ConfirmationCodeNotFoundError):
                    self._confirmation_codes.delete(confirmation_code.id)
                return False

            redis = self._confirmation_codes._redis
            stored_code = redis.hget(str(confirmation_code.id), "code")

            if not stored_code:
                logger.warning("Code not found in Redis: %s", confirmation_code.id)
                return False

            if int(stored_code) == code:
                incorrect_count = int(redis.hget(str(confirmation_code.id), "incorrect_count") or "0")

                if incorrect_count >= self.MAX_ATTEMPTS:
                    logger.info("Maximum attempts exceeded, deleting code")
                    self._confirmation_codes.delete(confirmation_code.id)
                    return False

                redis.hset(str(confirmation_code.id), "verified", "true")
                logger.info("Code %s verified: %s", action, verification_id)
                return True
            else:
                incorrect_count = int(redis.hget(str(confirmation_code.id), "incorrect_count") or "0")
                new_count = incorrect_count + 1
                redis.hset(
                    str(confirmation_code.id),
                    "incorrect_count",
                    str(new_count),
                )

                if new_count >= self.MAX_ATTEMPTS:
                    logger.info("Maximum attempts exceeded, deleting code")
                    self._confirmation_codes.delete(confirmation_code.id)
                else:
                    # Progressive delay before responding — slows brute-force
                    # attempts to under 30 codes/minute even if an attacker
                    # owns many `verification_id`s in parallel. Legitimate
                    # users who mistyped one digit see a 2s pause and one
                    # 5s pause before they're locked out — acceptable UX
                    # for the security gain. Blocks the event loop briefly
                    # (no asyncio.sleep — service method is sync); at our
                    # current scale this is fine. Move to async if we ever
                    # see >50 concurrent code-check requests per replica.
                    delay = 2 if new_count == 1 else 5
                    logger.info(
                        "Wrong code attempt %d/%d for verification_id %s — delaying %ds",
                        new_count,
                        self.MAX_ATTEMPTS,
                        verification_id,
                        delay,
                    )
                    time.sleep(delay)

                return False

        except ConfirmationCodeNotFoundError:
            logger.warning("Code not found for verification_id: %s", verification_id)
            return False

    def complete_registration(self, verification_id: UUID, password: str, name: str) -> AuthSessionDTO:
        logger.info("Completing registration for verification_id: %s", verification_id)

        try:
            query = ConfirmationCodeQueryDTO(
                registration_id=verification_id,
                action=ConfirmationCodeAction.REGISTER,
                is_temporary=True,
                code=None,
            )

            confirmation_code = self._confirmation_codes.get(query)

            if not confirmation_code.correct:
                raise AuthInvalidConfirmationCodeError("Code not verified")

            if confirmation_code.expires_at and confirmation_code.expires_at < datetime.now(UTC):
                raise AuthConfirmationCodeExpiredError("Code expired")

            contact = confirmation_code.contact
            if not contact:
                raise AuthInvalidConfirmationCodeError("Invalid confirmation code")
            existing_user = self._get_user_by_contact(contact)
            if existing_user:
                raise AuthUserExistsError("User already exists")

            register_dto = AuthRegisterDTO(
                email=contact if "@" in contact else None,
                phone=contact if "@" not in contact else None,
                password=password,
                name=name,
                platform=CodePlatform.WHATSAPP,
            )

            user_create_dto = to_user_create_dto(register_dto, is_active=True)

            try:
                user = self._users.create(user_create_dto)
                logger.info("User created: %s", user.id)
                try:
                    self._users.change_password(user.id, password)
                    logger.info("Password set for user: %s", user.id)
                except Exception as e:
                    logger.exception("Error setting password: %s", e)
                try:
                    self.identity_provider.update_user_subscription(
                        user_id=user.id,
                        plan=PlanType.PRO,
                        expires_at=user.subscription_end,
                    )
                    logger.info("Subscription LITE activated in Keycloak: %s", user.id)
                except Exception as e:
                    logger.exception("Error updating subscription in Keycloak: %s", e)
            except UserExistsError:
                raise AuthUserExistsError("User already exists")

            try:
                self.identity_provider.set_active(user.id, True)
                logger.info("User activated: %s", user.id)
            except Exception as e:
                logger.exception("Error activating user: %s", e)
                raise AuthFailedConfirmationError("Error activating user: %s", e)

            self._confirmation_codes.delete(confirmation_code.id)

            try:
                tokens = self._users.create_tokens(user.username, password)
                logger.info("Tokens created for user: %s", user.id)
            except Exception as e:
                logger.exception("Error creating tokens: %s", e)
                raise AuthFailedConfirmationError("Error creating tokens: %s", e)

            return to_auth_session_dto(tokens)

        except ConfirmationCodeNotFoundError:
            raise AuthInvalidConfirmationCodeError("Code not found or expired")
        except (AuthUserExistsError, AuthInvalidConfirmationCodeError, AuthConfirmationCodeExpiredError):
            raise
        except Exception as e:
            logger.exception(
                "Error completing registration: %s",
                e,
            )
            raise AuthFailedConfirmationError("Error completing registration: %s", e)

    def complete_password_reset(
        self, verification_id: UUID, new_password: str
    ) -> AuthSessionDTO:
        logger.info("Completing password reset for verification_id: %s", verification_id)

        try:
            query = ConfirmationCodeQueryDTO(
                registration_id=verification_id,
                action=ConfirmationCodeAction.RESET_PASSWORD,
                is_temporary=True,
                code=None,
            )

            confirmation_code = self._confirmation_codes.get(query)

            if not confirmation_code.correct:
                raise AuthInvalidConfirmationCodeError("Code not verified")

            if confirmation_code.expires_at and confirmation_code.expires_at < datetime.now(UTC):
                raise AuthConfirmationCodeExpiredError("Code expired")

            redis = self._confirmation_codes._redis
            real_user_id_str = redis.hget(str(confirmation_code.id), "real_user_id")

            if not real_user_id_str:
                contact = confirmation_code.contact
                if not contact:
                    raise AuthInvalidConfirmationCodeError("Invalid code")

                user = self._get_user_by_contact(contact)
                if not user:
                    raise AuthUserNotFoundError("User not found")

                user_id = user.id
            else:
                user_id = UUID(real_user_id_str.decode())

            # Always re-fetch the user so we have a usable contact for token
            # minting below, regardless of which branch above set user_id.
            user = self._users.get(to_user_query_dto(user_id=user_id))
            if not user:
                raise AuthUserNotFoundError("User not found")

            contact = user.phone or user.email
            if not contact:
                raise AuthFailedConfirmationError(
                    "User has neither phone nor email — cannot mint tokens"
                )

            self._users.change_password(user_id, new_password)
            logger.info("Password changed for user: %s", user_id)

            # Burn the confirmation code BEFORE side effects below so a retry
            # of this endpoint after a partial failure can't reuse it.
            self._confirmation_codes.delete(confirmation_code.id)

            # Revoke every active session/refresh token (Q: invalidate all
            # sessions on password reset = YES). If the password was reset
            # because the account was compromised, this kicks the attacker
            # out of any device they're signed in on. Best-effort: failure
            # here must not block the user from getting their new tokens,
            # since the password is already changed.
            try:
                self._users.logout_all_sessions(user_id)
            except Exception as e:
                logger.warning(
                    "Could not revoke existing sessions for %s after password reset: %s",
                    user_id,
                    e,
                )

            tokens = self._users.create_tokens(contact, new_password)
            logger.info("Tokens minted for user after password reset: %s", user_id)
            return to_auth_session_dto(tokens)

        except ConfirmationCodeNotFoundError:
            raise AuthInvalidConfirmationCodeError("Code not found or expired")
        except (
            AuthInvalidConfirmationCodeError,
            AuthConfirmationCodeExpiredError,
            AuthUserNotFoundError,
            AuthFailedConfirmationError,
        ):
            raise
        except Exception as e:
            logger.exception("Error resetting password: %s", e)
            raise AuthFailedConfirmationError("Error resetting password: %s", e)

    def check_subscription_status(self, user: UserDTO) -> dict:
        now = datetime.now(UTC)

        if user.plan == PlanType.PRO and user.subscription_end and user.subscription_end < now:
            try:
                update_data = UserUpdateDTO(plan=PlanType.FREE, subscription_end=None)
                self.update_user_profile(user, update_data)
                user.plan = PlanType.FREE
                user.subscription_end = None

                logger.info(
                    "PRO subscription expired, downgraded to FREE",
                    user_id=user.id,
                    action="subscription_expired",
                    previous_plan=PlanType.PRO,
                    new_plan=PlanType.FREE,
                )
            except Exception as e:
                logger.exception(
                    "Error downgrading user plan after subscription expiry: %s",
                    e,
                    user_id=user.id,
                    action="subscription_check",
                    error=str(e),
                )

        is_active = False
        if user.plan == PlanType.PRO:
            is_active = user.subscription_end and user.subscription_end > now
        elif user.plan == PlanType.FREE:
            is_active = True

        days_remaining = 0
        if user.plan == PlanType.PRO and user.subscription_end and is_active:
            days_remaining = max(0, (user.subscription_end - now).days)

        return {
            "plan": user.plan,
            "subscription_end": user.subscription_end,
            "is_active": is_active,
            "days_remaining": days_remaining,
        }

    def has_access(self, user: UserDTO, required_plan: PlanType | None = None) -> bool:
        status = self.check_subscription_status(user)

        if not status["is_active"]:
            return False

        if required_plan:
            return user.plan == required_plan

        return True

    def update_user_plan(self, user: UserDTO, plan: PlanType, duration_days: int) -> UserDTO:
        new_subscription_end = datetime.now(UTC) + timedelta(days=duration_days)

        update_data = UserUpdateDTO(
            plan=plan,
            subscription_end=new_subscription_end,
        )

        try:
            updated_user = self.update_user_profile(user, update_data)

            logger.info(
                "User's plan updated",
                user_id=user.id,
                action="update_plan",
                previous_plan=user.plan,
                new_plan=plan,
                duration_days=duration_days,
                new_subscription_end=new_subscription_end,
            )

            return updated_user

        except Exception as e:
            logger.exception(
                "Error updating user's plan",
                user_id=user.id,
                action="update_plan",
                error=str(e),
            )
            raise

    def activate_free_trial(self, user: UserDTO) -> UserDTO:
        return self.update_user_plan(user, PlanType.FREE, 3)

    # def activate_lite_subscription(self, user: UserDTO) -> UserDTO:
    #     return self.update_user_plan(user, PlanType.PRO, 30)

    def _is_email(self, contact: str) -> bool:
        return "@" in contact

    def _normalize_contact(self, contact: str) -> str:
        return contact.strip()

    def _is_reviewer_test_contact(self, contact: str) -> bool:
        """True if `contact` is in the reviewer-bypass list — meaning the
        SMSC call should be skipped and a fixed code (REVIEWER_TEST_CODE,
        default 123456) should be used instead.

        Env var `REVIEWER_TEST_PHONE` is a comma-separated list of phones,
        so the same bypass can hold both the App Store reviewer's number
        and the dev's working number at the same time. A single value
        (no commas) still works — that was the original shape.

        When `REVIEWER_TEST_PHONE` is unset the bypass is dormant and
        every code request goes through the real SMSC path — safe
        default for any environment that isn't actively in store-review
        or dev-testing.
        """
        raw = os.getenv("REVIEWER_TEST_PHONE")
        if not raw:
            return False
        return any(entry.strip() == contact for entry in raw.split(","))

    def _get_user_by_contact(self, contact: str) -> UserDTO | None:
        try:
            if self._is_email(contact):
                try:
                    keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(email=contact))
                    if keycloak_user.email and keycloak_user.email.lower() == contact.lower():
                        user = to_user_dto(
                            keycloak_user,
                            (keycloak_user.attributes.role if keycloak_user.attributes else []),
                        )
                        return user
                except IdentityNotFound:
                    return None

            else:
                normalized_phone = self._normalize_phone_for_search(contact)
                if not normalized_phone:
                    return None

                try:
                    keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(phone=normalized_phone))

                    if keycloak_user.attributes and keycloak_user.attributes.phone:
                        user_phones = keycloak_user.attributes.phone
                        for user_phone in user_phones:
                            if user_phone and self._normalize_phone_for_search(user_phone) == normalized_phone:
                                user = to_user_dto(
                                    keycloak_user,
                                    (keycloak_user.attributes.role if keycloak_user.attributes else []),
                                )
                                return user
                except IdentityNotFound:
                    return None

            return None

        except ValidationError as e:
            logger.exception(
                "Error retrieving user by contact %s: %s",
                contact,
                e,
            )
            return None
        except Exception as e:
            logger.exception("Error retrieving user by contact %s: %s", contact, e)
            return None

    def _normalize_phone_for_search(self, phone: str) -> str:
        if not phone:
            return ""

        phone = phone.replace(" ", "").replace("(", "").replace(")", "").replace("-", "")

        if phone.startswith("+") and phone.startswith("+77") and len(phone) == 12:
            return phone

        if phone.startswith("77") and len(phone) == 11:
            return "+" + phone

        if phone.startswith("8") and len(phone) == 11:
            return "+7" + phone[1:]

        if phone.isdigit() and len(phone) == 10:
            return "+7" + phone

        return phone

    def _send_confirmation_code(self, contact: str, code: int, platform: CodePlatform) -> bool:
        """Returns True iff the primary channel (SMS/Email/WhatsApp/Telegram)
        accepted the message. False means the dev fallback ran (or even that
        failed) — caller uses this to decide whether to apply the per-contact
        resend block."""
        message_text = f"Код подтверждения AIMA: {code}"

        try:
            message = NotificationMessageDTO(
                to=contact,
                message=message_text,
                platform=platform,
            )

            if platform == CodePlatform.EMAIL:
                self._email_client.notify(message)
                logger.info("Code sent via Email: %s", contact)
                return True
            elif platform == CodePlatform.SMS:
                try:
                    self._sms_client.notify(message)
                    logger.info("Code sent via SMS: %s", contact)
                    return True
                except Exception as e:
                    logger.exception("Error sending SMS: %s", e)
                    self._send_code_to_dev_channel(contact, code, "SMS", str(e))
                    return False
            elif platform == CodePlatform.WHATSAPP:
                try:
                    self._whatsapp_client.notify(message)
                    logger.info("Code sent via WhatsApp: %s", contact)
                    return True
                except Exception as e:
                    logger.exception("Error sending WhatsApp: %s", e)
                    self._send_code_to_dev_channel(contact, code, "WhatsApp", str(e))
                    return False
            elif platform == CodePlatform.TELEGRAM:
                self._notification_client.notify(message)
                logger.info("Code sent via Telegram: %s", contact)
                return True
            else:
                raise ValueError(f"Unsupported platform: {platform}")

        except Exception as e:
            # Q3=B + same principle for logs: never persist the actual code
            # in stdout/Sentry/Railway logs — that turned the dev-fallback
            # into a free auth bypass for anyone with log access.
            logger.exception("Error sending code (platform=%s): %s", platform, e)
            return False

    def _send_code_to_dev_channel(self, contact: str, code: int, source: str, error_msg: str = "") -> None:
        """Notify the dev/ops Telegram channel that primary delivery failed.
        Q3=B: never include the actual confirmation code or full contact in
        the message — anyone with read access to that channel could otherwise
        replay any code on any phone. We send only a partial mask of the
        contact for traceability + the underlying error.
        `code` is kept in the signature for API compatibility with callers
        but is intentionally NOT used in the body.
        """
        del code  # explicitly drop — never reaches Telegram or logs
        masked = _mask_contact(contact)
        try:
            dev_message = f"🔧 [DEV FALLBACK - {source}]\n"
            dev_message += f"📞 Контакт (маска): {masked}\n"
            if error_msg:
                dev_message += f"⚠️ Ошибка {source}: {error_msg[:200]}"
            else:
                dev_message += f"⚠️ Доставка через {source} провалилась"

            telegram_message = NotificationMessageDTO(
                to="",
                message=dev_message,
                platform=CodePlatform.TELEGRAM,
            )

            self._notification_client.notify(telegram_message)
            logger.info("Dev-channel alert sent (fallback %s) for %s", source, masked)

        except Exception as tg_e:
            # Even when Telegram itself fails we must not log the code.
            logger.exception(
                "Error sending dev-channel alert for %s (fallback %s): %s",
                masked,
                source,
                tg_e,
            )

    # def request_registration_code(self, contact: str, platform: CodePlatform) -> UUID:
    #     return self.request_code(contact, platform, ConfirmationCodeAction.REGISTER)

    # def check_registration_code(self, verification_id: UUID, code: int) -> bool:
    #     return self.check_code(verification_id, code, ConfirmationCodeAction.REGISTER)

    # def request_password_reset_code(self, contact: str, platform: CodePlatform) -> UUID:
    #     return self.request_code(
    #         contact, platform, ConfirmationCodeAction.RESET_PASSWORD
    #     )

    # def check_password_reset_code(self, verification_id: UUID, code: int) -> bool:
    #     return self.check_code(
    #         verification_id, code, ConfirmationCodeAction.RESET_PASSWORD
    #     )

    def login(self, params: AuthLoginDTO) -> AuthSessionDTO:
        logger.info("Login attempt: %s", params.login)
        try:
            tokens = self._users.create_tokens(params.login, params.password)
            logger.info("Login successful for: %s", params.login)
        except UserBadCredentialsError:
            logger.warning("Invalid credentials for: %s", params.login)
            raise AuthBadCredentialsError
        except UserNotVerifiedError:
            logger.warning("User not verified: %s", params.login)
            raise AuthNotVerifiedError

        return to_auth_session_dto(tokens)

    def refresh_token(self, refresh_token: str) -> AuthSessionDTO:
        logger.info("Refreshing token")
        try:
            tokens = self._users.refresh_token(refresh_token)
            logger.info("Token refreshed")
        except UserInvalidRefreshTokenError:
            logger.warning("Invalid refresh token")
            raise AuthInvalidRefreshTokenError

        return to_auth_session_dto(tokens)

    def logout(self, refresh_token: str) -> None:
        logger.info("Logout request")
        try:
            self._users.logout(refresh_token)
            logger.info("Logout successful")
        except UserInvalidRefreshTokenError:
            logger.warning("Invalid refresh token during logout")
            raise AuthInvalidRefreshTokenError

    def get_user_from_token(self, access_token: str) -> UserDTO:
        logger.debug("Getting user from token")
        try:
            user = self._users.get_user_from_token(access_token)
            logger.debug("User found by token: %s", user.id)
            return user
        except UserInvalidAccessTokenError:
            logger.warning("Invalid access token")
            raise AuthAccessInvalidTokenError

    def update_user_profile(
        self,
        user: UserDTO,
        data: UserUpdateDTO,
    ) -> UserDTO:
        logger.info("Updating profile for: %s", user.id)

        if data.email is not None and data.email == "":
            if not user.phone:
                raise ValueError(
                    "Cannot delete email. You must have at least one contact. Please add a phone number first or delete account."
                )
            logger.info("User deleting email, keeping phone")

        if data.phone is not None and data.phone == "":
            raise ValueError(
                "Cannot delete phone number. Phone number is required. If you want to remove your account, please use the delete account function."
            )

        if (data.email is not None and data.email == "") and (data.phone is not None and data.phone == ""):
            raise ValueError("Cannot delete all contacts. You must have at least one contact (phone number).")

        updated_email = data.email if data.email is not None else user.email
        updated_phone = data.phone if data.phone is not None else user.phone

        if not updated_phone and not updated_email:
            raise ValueError("User must have at least one contact (phone number is required)")

        if (data.phone is not None and not data.phone) and not updated_email:
            raise ValueError("Cannot remove phone number. Phone number is required. Please add an email first.")

        try:
            if hasattr(data, "avatar"):
                pass
            self._users.update(user, data)
            updated_user = self._users.get(to_user_query_dto(user_id=user.id))
            logger.info("Profile updated for: %s", user.id)
            return updated_user
        except UserNotFoundError:
            logger.exception("User not found during update: %s", user.id)
            raise AuthUserNotFoundError
        except UserEmailExistsError:
            logger.warning("Email already exists: %s", data.email)
            raise AuthUserEmailExistsError
        except UserPhoneExistsError:
            logger.warning("Phone already exists: %s", data.phone)
            raise AuthUserPhoneExistsError

    def delete_account(self, user: UserDTO) -> None:
        logger.info("Deleting account: %s", user.id)
        try:
            self.identity_provider.delete(user.id)
            logger.info("Account deleted: %s", user.id)
        except IdentityNotFound:
            logger.exception("User not found during deletion: %s", user.id)
            raise AuthUserNotFoundError
        except Exception as e:
            logger.exception("Unexpected error during deletion: %s", str(e))
            raise AuthUserNotFoundError

    def is_admin(self, user: UserDTO) -> bool:
        is_admin = "admin" in user.roles
        logger.debug("Checking admin for %s: %s", user.id, is_admin)
        return is_admin

    def login_via_oauth(self, code: str, provider: OAuthProviders) -> AuthSessionDTO:
        try:
            logger.info("Starting OAuth %s with code: %s", provider, code[:10])

            email, name = self.oauth_helper.extract_user_info(provider, code)
            logger.info("Processing OAuth %s user: %s <%s>", provider, name, email)

            tokens = self.oauth_helper.handle_oauth_user(email, name, provider)
            logger.info("%s OAuth successful for: %s", provider, email)

            return to_auth_session_dto(tokens)

        except Exception as e:
            logger.exception("%s OAuth failed: %s", provider, str(e))
            self._handle_oauth_error(e, provider)

    def _handle_oauth_error(self, error: Exception, provider: str):
        error_msg = str(error).lower()

        if "invalid_grant" in error_msg:
            raise ValueError(f"Invalid authorization code {provider}")
        elif "invalid_token" in error_msg:
            raise ValueError(f"Invalid token ID {provider}")
        elif "not found" in error_msg:
            raise ValueError("User not found")
        else:
            raise ValueError(f"Authentificated error {provider}: {str(error)}")

    def change_password(self, user_id: UUID, old_password: str, new_password: str) -> None:
        logger.info("Change password for user: %s", user_id)

        try:
            user = self._users.get(to_user_query_dto(user_id=user_id))
            if not user:
                raise AuthUserNotFoundError("User not found")

            contact = user.email or user.phone
            if not contact:
                raise AuthBadCredentialsError("User don't have email or phone")

            try:
                self._users.create_tokens(contact, old_password)
                logger.info("Current password checked successfully: %s", user_id)
            except UserBadCredentialsError:
                logger.warning("Invalid current password")
                raise AuthBadCredentialsError("Invalid current password")

            self._users.change_password(user_id, new_password)
            logger.info("Password successfully changed for %s", user_id)

        except UserNotFoundError:
            raise AuthUserNotFoundError("User not found")
        except Exception as e:
            logger.exception("Error while updating password: %s", e)
            raise

    def change_contact_request(self, user_id: UUID, contact: str, platform: CodePlatform) -> UUID:
        logger.info("Request for change contact for %s, new contact: %s", user_id, contact)

        contact = contact.strip()

        current_user = self._users.get(to_user_query_dto(user_id=user_id))
        if not current_user:
            raise AuthUserNotFoundError("User not found")

        if "@" in contact:
            contact = contact.lower()

            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, contact):
                raise ValueError(
                    "Invalid email format: must be a valid email address with name, '@' symbol, and domain"
                )

            if current_user.email and current_user.email.lower() == contact:
                raise ValueError("New contact equaled to current contact")

            existing_user = self._get_user_by_contact(contact)
            if existing_user and existing_user.id != user_id:
                logger.warning(
                    "Email %s already linked by another user: %s",
                    contact,
                    existing_user.id,
                )
                raise AuthUserEmailExistsError("Email already used by another user")

            action = ConfirmationCodeAction.CHANGE_EMAIL

        else:
            contact = self._normalize_phone_for_search(contact)

            phone_pattern = r"^\+77\d{9}$"
            if not re.match(phone_pattern, contact):
                raise ValueError("Phone must be a valid Kazakhstan mobile number (+77XXXXXXXXX)")

            if current_user.phone and self._normalize_phone_for_search(current_user.phone) == contact:
                raise ValueError("New contact equaled to current contact")

            existing_user = self._get_user_by_contact(contact)
            if existing_user and existing_user.id != user_id:
                logger.warning(
                    "Phone number %s already linked by another user: %s",
                    contact,
                    existing_user.id,
                )
                raise AuthUserPhoneExistsError("Phone number already used by another user")

            action = ConfirmationCodeAction.CHANGE_PHONE

        verification_id = self.request_code(contact, platform, action)

        try:
            query = ConfirmationCodeQueryDTO(
                registration_id=verification_id,
                action=action,
                is_temporary=True,
                code=None,
            )
            confirmation_code = self._confirmation_codes.get(query)

            redis = self._confirmation_codes._redis
            redis.hset(str(confirmation_code.id), "user_id", str(user_id))
            redis.hset(str(confirmation_code.id), "real_user_id", str(user_id))

            contact_type = "email" if "@" in contact else "phone"
            redis.hset(str(confirmation_code.id), "contact_type", contact_type)

            logger.info(
                "Verification code for change contact send. Verification ID: %s",
                verification_id,
            )

        except ConfirmationCodeNotFoundError:
            logger.exception("Verification code doesn't find after creating: %s", verification_id)
            raise AuthInvalidConfirmationCodeError("Error while creating verification code")

        return verification_id

    def change_contact_confirm(self, verification_id: UUID, code: int) -> UserDTO:
        logger.info("Confirmation changing contact. Verification_id: %s", verification_id)

        actions_to_try = [
            ConfirmationCodeAction.CHANGE_EMAIL,
            ConfirmationCodeAction.CHANGE_PHONE,
        ]

        valid_action = None
        confirmation_code = None

        for action in actions_to_try:
            try:
                is_valid = self.check_code(verification_id, code, action)
                if is_valid:
                    valid_action = action
                    query = ConfirmationCodeQueryDTO(
                        registration_id=verification_id,
                        action=action,
                        is_temporary=True,
                        code=None,
                    )
                    confirmation_code = self._confirmation_codes.get(query)
                    break
            except ConfirmationCodeNotFoundError as e:
                logger.warning("Something happened: %s", e)
            except Exception as e:
                logger.warning("Something happened: %s", e)

        if not valid_action or not confirmation_code:
            raise AuthInvalidConfirmationCodeError("Invalid confirmation code")

        redis = self._confirmation_codes._redis
        verified = redis.hget(str(confirmation_code.id), "verified")
        if not verified or verified.decode("utf-8") != "true":
            raise AuthInvalidConfirmationCodeError("Confirmation code not verified")

        user_id = None
        user_id_str = redis.hget(str(confirmation_code.id), "real_user_id")

        if not user_id_str:
            user_id_str = redis.hget(str(confirmation_code.id), "user_id")

        if user_id_str:
            user_id_str_decoded = user_id_str.decode("utf-8")
            user_id = UUID(user_id_str_decoded)
        else:
            user_id = confirmation_code.user_id

        if not user_id:
            raise AuthInvalidConfirmationCodeError("Confirmation error: user_id not found")

        user = self._users.get(to_user_query_dto(user_id=user_id))
        if not user:
            raise AuthUserNotFoundError("User not found")

        new_contact = confirmation_code.contact
        if not new_contact:
            raise AuthInvalidConfirmationCodeError("Invalid confirmation code")

        existing_user = self._get_user_by_contact(new_contact)
        if existing_user and existing_user.id != user_id:
            if "@" in new_contact:
                logger.warning("Email %s now using by %s", new_contact, existing_user.id)
                raise AuthUserEmailExistsError(
                    "Email now using by another user. Please, request confirmation code later"
                )
            else:
                logger.warning("Phone number %s now using by %s", new_contact, existing_user.id)
                raise AuthUserPhoneExistsError(
                    "Phone number now using by another user. Please, request confirmation code later"
                )

        contact_type = redis.hget(str(confirmation_code.id), "contact_type")
        if contact_type:
            contact_type = contact_type.decode("utf-8")

        if valid_action == ConfirmationCodeAction.CHANGE_EMAIL or contact_type == "email":
            update_data = UserUpdateDTO(email=new_contact)
        else:
            update_data = UserUpdateDTO(phone=new_contact)

        updated_user = self.update_user_profile(user, update_data)

        self._confirmation_codes.delete(confirmation_code.id)

        logger.info(
            "Contact successfully changed for %s, actual contact: %s",
            user_id,
            new_contact,
        )

        return updated_user
