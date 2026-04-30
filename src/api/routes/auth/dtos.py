import re
from uuid import UUID

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)

from auth.dtos.confirmation_codes import ConfirmationCodeAction
from clients.notification import CodePlatform
from utils.validators import KZPhone


class RegisterParamsDTO(BaseModel):
    """Legacy registration parameters (deprecated)"""

    name: str
    phone: KZPhone
    email: EmailStr
    password: str
    platform: CodePlatform


class RegistrationCompleteDTO(BaseModel):
    """Complete registration after code verification"""

    verification_id: UUID = Field(..., description="Verified code ID")
    password: str = Field(..., min_length=6, description="User password")
    name: str = Field(..., min_length=2, max_length=100, description="User display name")


class AuthConfirmRegistrationParamsDTO(BaseModel):
    """Legacy registration confirmation (deprecated)"""

    registration_id: UUID
    code: int


class LoginParamsDTO(BaseModel):
    """Login credentials"""

    login: str = Field(..., description="Email or phone number")
    password: str = Field(..., description="Password")


class LogoutParamsDTO(BaseModel):
    """Logout request"""

    refresh_token: str = Field(..., description="Refresh token to invalidate")


class RefreshTokenParamsDTO(BaseModel):
    """Refresh token request"""

    refresh_token: str = Field(..., description="Refresh token")


class TokensDTO(BaseModel):
    """Authentication tokens"""

    access_token: str
    refresh_token: str
    # expires_in: int
    # token_type: str = "bearer"


class AuthConfirmResetPasswordParamsDTO(BaseModel):
    """Legacy password reset confirmation (deprecated)"""

    user_id: UUID
    code: int
    password: str


class PasswordResetCompleteDTO(BaseModel):
    """Complete password reset after code verification"""

    verification_id: UUID = Field(..., description="Verified code ID")
    new_password: str = Field(..., min_length=6, description="New password")


class ResetPasswordDTO(BaseModel):
    """Legacy password reset request (deprecated)"""

    phone: KZPhone
    platform: CodePlatform


class ResendCodeDTO(BaseModel):
    """Legacy code resend (deprecated)"""

    registration_id: UUID
    platform: CodePlatform


class UpdateProfileDTO(BaseModel):
    """Legacy profile update (deprecated)"""

    name: str | None = Field(None, form_field=True)
    email: EmailStr | None = Field(None, form_field=True)
    phone: str | None = Field(None, form_field=True)
    avatar: str | None = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_formdata(cls, form_data: dict) -> "UpdateProfileDTO":
        """Create DTO from form data (legacy)"""
        return cls(**{k: v for k, v in form_data.items() if v not in (None, "")})


class CodeRequestDTO(BaseModel):
    """Request confirmation code for various actions"""

    contact: str = Field(..., description="Email or phone number")
    platform: CodePlatform = Field(..., description="Platform to send code")
    action: ConfirmationCodeAction = Field(..., description="Action type")

    @field_validator("contact")
    def validate_contact(cls, v: str, info: ValidationInfo) -> str:
        """Validate contact based on action"""
        action = info.data.get("action") if info.data else None

        if action == ConfirmationCodeAction.REGISTER:
            if "@" in v:
                email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
                if not re.match(email_pattern, v):
                    raise ValueError("Invalid email format")
            else:
                phone_pattern = r"^\+77\d{9}$"
                if not re.match(phone_pattern, v):
                    raise ValueError("Phone must be a valid Kazakhstan mobile number (+77XXXXXXXXX)")

        return v


class CodeCheckDTO(BaseModel):
    """Check confirmation code"""

    verification_id: UUID = Field(..., description="Verification ID from code request")
    code: int = Field(..., description="Confirmation code to check")
    action: ConfirmationCodeAction = Field(..., description="Action type")


class RegistrationRequestCodeDTO(BaseModel):
    """Legacy registration code request (deprecated)"""

    contact: str
    platform: CodePlatform


class RegistrationCheckCodeDTO(BaseModel):
    """Legacy registration code check (deprecated)"""

    verification_id: UUID
    code: int


class PasswordResetRequestCodeDTO(BaseModel):
    """Legacy password reset code request (deprecated)"""

    contact: str
    platform: CodePlatform


class PasswordResetCheckCodeDTO(BaseModel):
    """Legacy password reset code check (deprecated)"""

    verification_id: UUID
    code: int


class ChangePasswordDTO(BaseModel):
    """Change password for authenticated user"""

    old_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=6, description="New password")


class ContactChangeRequest(BaseModel):
    """Request verification code for contact change"""

    contact: str = Field(..., description="New email or phone number")
    platform: CodePlatform = Field(..., description="Platform to send verification code")


class ContactChangeConfirmRequest(BaseModel):
    """Confirm contact change with verification code"""

    verification_id: UUID = Field(..., description="Verification ID from change request")
    code: int = Field(..., description="Verification code")


class ConfirmationDTO(BaseModel):
    """Confirmation response"""

    verification_id: UUID
    # expires_in: int = 600


class ErrorResponse(BaseModel):
    """Standard error response"""

    detail: str = Field(..., description="Error description")


class SuccessResponse(BaseModel):
    """Standard success response"""

    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


class CodeRequestResponse(BaseModel):
    """Response for code request"""

    verification_id: UUID = Field(..., description="Verification ID for the requested code")


class CodeCheckResponse(BaseModel):
    """Response for code check"""

    valid: bool = Field(..., description="Code validity status")


class PasswordResetResponse(BaseModel):
    """Response for password reset completion"""

    success: bool = Field(True, description="Reset success status")
    message: str = Field("Password has been reset successfully", description="Reset message")


class OAuthStartResponse(BaseModel):
    """Response for OAuth flow start"""

    oauth_url: str = Field(..., description="OAuth authorization URL")
    state: str = Field(..., description="OAuth state parameter for CSRF protection")
    redirect_after_auth: str = Field(..., description="Redirect URL after authentication")
    expires_in: int = Field(300, description="State expiration time in seconds")


class OAuthCallbackResponse(BaseModel):
    """Response for OAuth callback"""

    access_token: str = Field(..., description="Access token")
    refresh_token: str = Field(..., description="Refresh token")
    redirect_url: str = Field(..., description="Redirect URL to frontend")
    provider: str = Field(..., description="OAuth provider name")
