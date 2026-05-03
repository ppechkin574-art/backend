import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CardStyleDTO(BaseModel):
    id: int
    guid: str
    name: str
    is_active: bool


class CardStyleCreateDTO(BaseModel):
    name: str = Field(..., max_length=100)
    is_active: bool = True


class CardStyleUpdateDTO(BaseModel):
    name: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class UserBankAccountDTO(BaseModel):
    guid: str
    student_guid: str
    card_style_id: int
    card_number: str
    balance: int
    created_at: datetime

    @field_validator("card_number", mode="before")
    @classmethod
    def mask_card_number(cls, v):
        if isinstance(v, str) and len(v) >= 4:
            return f"**** {v[-4:]}"
        return v


class UpdateCardStyleRequestDTO(BaseModel):
    card_style_id: int


class TransactionDTO(BaseModel):
    guid: str
    type: str
    amount: int
    description: str | None
    status: str
    created_at: datetime
    additional_metadata: dict | None = None


class WithdrawalRequestCreateDTO(BaseModel):
    amount: int = Field(..., ge=100)
    iban: str = Field(..., max_length=50)
    card_number: str = Field(..., max_length=19)
    card_holder: str = Field(..., max_length=200)
    iin: str = Field(..., max_length=12)

    @field_validator("card_number")
    @classmethod
    def validate_card_number(cls, v):
        if not re.match(r"^\d{16}$", v.replace(" ", "")):
            raise ValueError("Card number must be a 16-digit number")
        return v

    @field_validator("iin")
    @classmethod
    def validate_iin(cls, v):
        if not re.match(r"^\d{12}$", v):
            raise ValueError("IIN must be a 12-digit number")
        return v


class WithdrawalRequestDTO(BaseModel):
    guid: str
    account_guid: str
    amount: int
    iban: str
    card_number: str
    card_holder: str
    iin: str
    status: str
    admin_comment: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class WithdrawalRequestUpdateDTO(BaseModel):
    status: Literal["pending", "approved", "rejected", "cancelled"]
    comment: str | None = None


class AccountOperationResponseDTO(BaseModel):
    student_guid: str
    card_style_id: int
    card_number: str
    balance: int
    message: str = "Successfully processed"
