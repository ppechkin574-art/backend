from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StudentDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rating: int


class StudentCreateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rating: int = Field(default=0)
