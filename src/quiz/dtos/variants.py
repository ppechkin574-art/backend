from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quiz.dtos.text_blocks import (
    TextBlockRepositoryDTO,
    TextBlockServiceDTO,
)

if TYPE_CHECKING:
    from quiz.models.edu_content import Variant


class VariantRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID | None
    question_id: int
    blocks: list[TextBlockRepositoryDTO]
    is_correct: bool
    weight: float | None = None

    @staticmethod
    def custom(v: "Variant"):
        blocks = []
        if v.link and v.link.blocks:
            blocks = [TextBlockRepositoryDTO.model_validate(b) for b in sorted(v.link.blocks, key=lambda x: x.order)]

        return VariantRepositoryDTO(
            id=v.id,
            guid=v.guid,
            question_id=v.question_id,
            blocks=blocks,
            is_correct=v.is_correct,
            weight=v.weight,
        )


class VariantCreateRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    blocks: list[TextBlockRepositoryDTO]
    blocks: list[TextBlockRepositoryDTO]
    is_correct: bool
    weight: float | None = None


class VariantCreateServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = None
    blocks: list[TextBlockRepositoryDTO]
    blocks: list[TextBlockRepositoryDTO]
    is_correct: bool
    weight: float | None = None


class VariantServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)

    id: int
    blocks: list[TextBlockServiceDTO]
    is_correct: bool
    weight: float | None = None


class ImportVariantCreateDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    blocks: list[TextBlockServiceDTO]
    blocks: list[TextBlockServiceDTO]
    is_correct: bool
    weight: float | None = None


class VariantUpdateRepositoryDTO(BaseModel):
    id: int | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    is_correct: bool | None = None
    weight: float | None = None


class VariantUpdateServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    is_correct: bool | None = None
    weight: float | None = None
