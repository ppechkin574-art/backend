from uuid import UUID


class AuthError(Exception):
    """Auth error class for authentication service"""


class AuthUserExistsError(AuthError):
    """Authentication service if user exists"""


class AuthUserNotFoundError(AuthError):
    """Authentication service if user not found"""


class AuthUserEmailExistsError(AuthError):
    """When authentication user email already exists"""


class AuthUserPhoneExistsError(AuthError):
    """When authentication user phone already exists"""


class AuthFailedConfirmationError(AuthError):
    """Authentication service if failed to confirm sending code"""


class AuthBadCredentialsError(AuthError):
    """Authentication service if bad credentials input"""


class AuthUnauthorizedError(AuthError):
    """Authentication service if unauthorized access"""


class AuthAccessInvalidTokenError(AuthError):
    """Authentication service if invalid access token passed"""


class AuthInvalidRefreshTokenError(AuthError):
    """Authentication service if invalid refresh token passed"""


class AuthNotVerifiedError(AuthError):
    pass


class UserError(AuthError):
    """User error class for users repository"""


class UserNotFoundError(UserError):
    """Users repository if user not found"""


class UserEmailExistsError(UserError):
    """When user email is already exists in repository"""


class UserPhoneExistsError(UserError):
    """When user phone is already exists in repository"""


class UserExistsError(UserError):
    """
    Users repository if user exists

    Args:
        is_active (bool): If user exist, but not active
        user_id: Existing user's id
    """

    is_active: bool
    user_id: UUID

    def __init__(self, user_id: UUID, is_active: bool):
        self.user_id = user_id
        self.is_active = is_active


class UserBadCredentialsError(UserError):
    """Users repository if bad (phone, password) credentials"""


class UserInvalidAccessTokenError(UserError):
    """Users repository if invalid access token passed"""


class UserInvalidRefreshTokenError(UserError):
    """Users repository if invalid refresh token passed"""


class UserNotVerifiedError(UserError):
    pass


class ConfirmationCodeError(AuthError):
    """Confirmation codes class error in confirmation codes repository"""


class ConfirmationCodeExistsError(ConfirmationCodeError):
    """
    Confirmation codes repository if code exists

    Args:
        confirmation_code_id (UUID): id of existing confirmation code.
    """

    confirmation_code_id: UUID

    def __init__(self, confirmation_code_id: UUID, message: str = None):
        self.confirmation_code_id = confirmation_code_id
        super().__init__(message)


class ConfirmationCodeNotFoundError(ConfirmationCodeError):
    """Confirmation codes repository if code not found"""


class TemporaryRegistrationNotFoundError(ConfirmationCodeError):
    """not found"""


class AuthInvalidConfirmationCodeError(ConfirmationCodeError):
    """Invalid confirmation code provided."""

    detail = "Invalid confirmation code"


class AuthConfirmationCodeExpiredError(ConfirmationCodeError):
    """Confirmation code has expired."""

    detail = "Confirmation code has expired"
