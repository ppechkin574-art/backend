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


def localize_hint_blocks_with_kk_text(
    blocks: list[TextBlockRepositoryDTO],
    kk_text: str | None,
) -> list[TextBlockRepositoryDTO]:
    """Mirror of `quiz.dtos.questions.localize_blocks_with_kk_text` but
    typed for the Repository-level block model used inside hints.

    Returns a new list with the leading text block's `value` swapped to
    `kk_text`.  When the hint has no text blocks at all, prepend one.
    No-op when `kk_text` is empty/None.

    Kept in this module (rather than importing the questions-level
    helper) to avoid the Repository ↔ Service DTO mismatch — both shapes
    have `id/order/type/value` so structurally identical, but the type
    annotations need to line up at each call site.
    """
    if not kk_text:
        return blocks

    # BlockType is shared across DTO layers — re-import here to keep
    # this module free of upward dependencies on `quiz.dtos.questions`.
    from quiz.dtos.enums import BlockType

    new_blocks: list[TextBlockRepositoryDTO] = []
    replaced = False
    for block in blocks:
        if not replaced and block.type == BlockType.text:
            new_blocks.append(
                TextBlockRepositoryDTO(
                    id=block.id,
                    order=block.order,
                    type=BlockType.text,
                    value=kk_text,
                )
            )
            replaced = True
        else:
            new_blocks.append(block)

    if not replaced:
        shifted = [
            TextBlockRepositoryDTO(
                id=b.id,
                order=b.order + 1,
                type=b.type,
                value=b.value,
            )
            for b in blocks
        ]
        new_blocks = [
            TextBlockRepositoryDTO(
                id=None,
                order=0,
                type=BlockType.text,
                value=kk_text,
            ),
            *shifted,
        ]

    return new_blocks
