class IdentityProviderError(Exception):
    """Identity provider error class"""


class IdentityBadCredentials(IdentityProviderError):
    """If phone and password is bad."""


class InvalidAccessTokenError(IdentityProviderError):
    """If access token passed is invalid."""


class NotVerifiedError(IdentityProviderError):
    pass


class InvalidRefreshTokenError(IdentityProviderError):
    """If refresh token passed is invalid."""


class IdentityNotFound(IdentityProviderError):
    """If requested identity was not found."""


class EmailAlreadyExists(IdentityProviderError):
    """When updating email already exists."""
