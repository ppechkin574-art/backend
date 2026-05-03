from pydantic import BaseModel, EmailStr, Field

from auth.dtos.users import UserDTO
from utils.validators import KZPhone


class AdminUserCreateDTO(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: KZPhone | None = None
    password: str | None = Field(None, min_length=6)
    role: str = Field(..., pattern="^(admin|teacher)$")
    allowed_subject_ids: list[int] | None = Field(default_factory=list)


class AdminUserUpdateDTO(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: KZPhone | None = None
    password: str | None = Field(None, min_length=6)
    allowed_subject_ids: list[int] | None = None
    is_active: bool | None = None


class AdminUserCreateResponseDTO(UserDTO):
    generated_password: str | None = None
