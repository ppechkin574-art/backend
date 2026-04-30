from typing import Any

from api.routes.auth.dtos import (
    CodeCheckResponse,
    CodeRequestResponse,
    ConfirmationDTO,
    ErrorResponse,
    OAuthCallbackResponse,
    OAuthStartResponse,
    PasswordResetResponse,
    TokensDTO,
)
from auth.dtos.users import UserDTO

UNAUTHORIZED_RESPONSE: dict[int, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Invalid or expired token"}
}

FORBIDDEN_RESPONSE: dict[int, dict[str, Any]] = {
    403: {"model": ErrorResponse, "description": "Insufficient permissions"}
}

BAD_REQUEST_RESPONSE: dict[int, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid request parameters"}
}

NOT_FOUND_RESPONSE: dict[int, dict[str, Any]] = {404: {"model": ErrorResponse, "description": "Resource not found"}}


code_request_responses: dict[int, dict[str, Any]] = {
    200: {"model": CodeRequestResponse, "description": "Code requested successfully"},
    400: {
        "model": ErrorResponse,
        "description": "Invalid contact format or user exists",
    },
    429: {"model": ErrorResponse, "description": "Too many requests"},
}

code_check_responses: dict[int, dict[str, Any]] = {
    200: {"model": CodeCheckResponse, "description": "Code check result"},
    400: {"model": ErrorResponse, "description": "Invalid verification ID or code"},
    404: {"model": ErrorResponse, "description": "Code not found or expired"},
}

registration_complete_responses: dict[int, dict[str, Any]] = {
    200: {"model": TokensDTO, "description": "Registration completed successfully"},
    400: {"model": ErrorResponse, "description": "Invalid code or user already exists"},
    404: {"model": ErrorResponse, "description": "Code not found or expired"},
}

password_reset_complete_responses: dict[int, dict[str, Any]] = {
    200: {"model": PasswordResetResponse, "description": "Password reset successfully"},
    400: {"model": ErrorResponse, "description": "Invalid code or weak password"},
    404: {"model": ErrorResponse, "description": "Code not found or user not found"},
}


login_responses: dict[int, dict[str, Any]] = {
    200: {"model": TokensDTO, "description": "Login successful"},
    401: {"model": ErrorResponse, "description": "Invalid credentials"},
    403: {"model": ErrorResponse, "description": "User not verified or account locked"},
}

logout_responses: dict[int, dict[str, Any]] = {
    204: {"description": "Logout successful"},
    400: {"model": ErrorResponse, "description": "Invalid refresh token"},
}

refresh_responses: dict[int, dict[str, Any]] = {
    200: {"model": TokensDTO, "description": "Token refreshed successfully"},
    401: {"model": ErrorResponse, "description": "Invalid or expired refresh token"},
}


profile_get_responses: dict[int, dict[str, Any]] = {
    200: {"model": UserDTO, "description": "User profile retrieved successfully"},
    401: UNAUTHORIZED_RESPONSE[401],
}

profile_put_responses: dict[int, dict[str, Any]] = {
    200: {"model": UserDTO, "description": "Profile updated successfully"},
    400: {"model": ErrorResponse, "description": "Invalid data or contact conflicts"},
    401: UNAUTHORIZED_RESPONSE[401],
    404: {"model": ErrorResponse, "description": "User not found"},
}


change_password_responses: dict[int, dict[str, Any]] = {
    204: {"description": "Password changed successfully"},
    400: {
        "model": ErrorResponse,
        "description": "Invalid current password or weak new password",
    },
    401: UNAUTHORIZED_RESPONSE[401],
    404: {"model": ErrorResponse, "description": "User not found"},
}


contact_change_request_responses: dict[int, dict[str, Any]] = {
    200: {
        "model": ConfirmationDTO,
        "description": "Verification code sent successfully",
    },
    400: {
        "model": ErrorResponse,
        "description": "Invalid contact or contact already in use",
    },
    401: UNAUTHORIZED_RESPONSE[401],
    404: {"model": ErrorResponse, "description": "User not found"},
}

contact_change_confirm_responses: dict[int, dict[str, Any]] = {
    200: {"model": UserDTO, "description": "Contact changed successfully"},
    400: {
        "model": ErrorResponse,
        "description": "Invalid or expired verification code",
    },
    401: UNAUTHORIZED_RESPONSE[401],
    404: {"model": ErrorResponse, "description": "User or code not found"},
    409: {
        "model": ErrorResponse,
        "description": "Contact already in use by another user",
    },
}


delete_account_responses: dict[int, dict[str, Any]] = {
    204: {"description": "Account deleted successfully"},
    401: UNAUTHORIZED_RESPONSE[401],
    404: {"model": ErrorResponse, "description": "User not found"},
}


oauth_start_responses: dict[int, dict[str, Any]] = {
    200: {
        "description": "OAuth flow started",
        "model": OAuthStartResponse,
    },
    404: {"model": ErrorResponse, "description": "Unsupported OAuth provider"},
}

oauth_callback_responses: dict[int, dict[str, Any]] = {
    200: {
        "description": "OAuth authentication successful",
        "model": OAuthCallbackResponse,
    },
    400: {"model": ErrorResponse, "description": "Invalid OAuth code or state"},
}


register_responses: dict[int, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid registration data"}
}

confirm_registration_responses: dict[int, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid confirmation code"}
}

reset_password_responses: dict[int, dict[str, Any]] = {404: {"model": ErrorResponse, "description": "User not found"}}

confirm_reset_password_responses: dict[int, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid reset code"}
}
