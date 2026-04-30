from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr, model_validator

from clients.notification import CodePlatform
from utils.validators import KZPhone


class AuthLoginDTO(BaseModel):
    login: str
    password: str


class AuthRegisterDTO(BaseModel):
    name: str
    phone: KZPhone | None = None
    email: EmailStr | None = None
    password: str
    platform: CodePlatform

    @model_validator(mode="after")
    def validate_credentials(self):
        if self.platform == CodePlatform.EMAIL and (not self.email or not self.password):
            raise ValueError("Email and password are required for email registration")
        elif (
            self.platform
            in [
                CodePlatform.WHATSAPP,
                CodePlatform.SMS,
                # CodePlatform.TELEGRAM,
            ]
            and not self.phone
        ):
            raise ValueError("Phone is required for phone-based registration")
        return self


class AuthConfirmationCodeDTO(BaseModel):
    registration_id: UUID
    code: int


class AuthSessionDTO(BaseModel):
    access_token: str
    refresh_token: str


class AuthResetPasswordDTO(BaseModel):
    email: EmailStr
    platform: CodePlatform


class OAuthProviders(StrEnum):
    GOOGLE = "google"
    APPLE = "apple"
