from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quiz.dtos.text_blocks import (
    TextBlockRepositoryDTO,
    TextBlockServiceDTO,
)

if TYPE_CHECKING:
    from quiz.models.edu_content import Hint


class HintCreateRepositoryDTO(BaseModel):
    blocks: list[TextBlockRepositoryDTO]


class HintRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID | None
    blocks: list[TextBlockRepositoryDTO]

    @staticmethod
    def custom(h: "Hint"):
        blocks = []
        if h.link and h.link.blocks:
            blocks = [TextBlockRepositoryDTO.model_validate(b) for b in sorted(h.link.blocks, key=lambda x: x.order)]

        return HintRepositoryDTO(id=h.id, guid=h.guid, blocks=blocks)


class HintCreateServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    blocks: list[TextBlockRepositoryDTO]


class HintServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    blocks: list[TextBlockServiceDTO]


class HintUpdateRepositoryDTO(BaseModel):
    blocks: list[TextBlockRepositoryDTO] | None = None


class HintUpdateServiceDTO(BaseModel):
    blocks: list[TextBlockRepositoryDTO] | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
