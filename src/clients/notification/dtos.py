from enum import StrEnum

from pydantic import BaseModel, EmailStr


class CodePlatform(StrEnum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"


class NotificationMessageDTO(BaseModel):
    to: str
    message: str
    platform: CodePlatform


class EmailMessageDTO(BaseModel):
    to: EmailStr
    subject: str
    message: str
    from_email: str
