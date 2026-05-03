from pydantic import BaseModel, ConfigDict

from quiz.dtos.enums import BlockType


class TextBlockServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    order: int
    type: BlockType
    value: str


class TextBlockRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    order: int
    type: BlockType
    value: str


class TextBlockCreateDTO(BaseModel):
    order: int
    type: BlockType
    value: str
