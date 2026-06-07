"""Wire / service shapes for the question-draft review pipeline.

Three DTOs, mirroring the leaderboard-prize feature's style:
- `QuestionDraftCreateDTO` — what the generator tool POSTs.
- `QuestionDraftUpdateDTO` — partial edit before publish (all optional).
- `QuestionDraftReadDTO`   — what the admin reads back (from_attributes).

The `blocks` / `variants` payloads are kept loosely typed (`DraftBlock`,
`DraftVariant`) so the generator can hand us content without first
matching the live TextBlock DTO shape exactly — the service normalizes
them into `QuestionCreateServiceDTO` blocks/variants at publish time.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quiz.dtos.enums import BlockType, Difficulty, DraftStatus, QuestionType


class DraftBlock(BaseModel):
    """A single content block of the question (or of a variant)."""

    type: BlockType = BlockType.text
    order: int = 0
    value: str


class DraftVariant(BaseModel):
    """An answer option.

    Either supply `value` (a single text block is synthesized at
    publish) OR a full `blocks` list (for media / multi-block options).
    `is_correct` is required; `weight` is optional — publish fills a
    sane default when omitted.
    """

    value: str | None = None
    blocks: list[DraftBlock] | None = None
    is_correct: bool = False
    weight: float | None = None


class DraftSource(BaseModel):
    """Provenance of the draft from the source textbook."""

    book: str | None = None
    chapter: str | None = None
    page: str | int | None = None


class QuestionDraftCreateDTO(BaseModel):
    """Payload the generator tool sends to create a draft."""

    subject_id: int | None = None
    subject_name: str | None = None
    topic_name: str | None = None
    difficulty: Difficulty | None = None
    question_type: QuestionType = QuestionType.single_choice

    blocks: list[DraftBlock] = Field(default_factory=list)
    variants: list[DraftVariant] = Field(default_factory=list)

    task_description_ru: str | None = None
    task_description_kk: str | None = None
    question_translation_ru: str | None = None
    question_translation_kk: str | None = None
    explanation_ru: str | None = None
    explanation_kk: str | None = None

    source: DraftSource | None = None
    validation: dict | None = None
    dedup_of_question_id: int | None = None
    # Initial status — generators normally leave this as `draft`, but the
    # tool may pre-mark trusted output as `approved`.
    status: DraftStatus = DraftStatus.draft


class QuestionDraftUpdateDTO(BaseModel):
    """Partial edit applied by the reviewer before publishing. Every
    field optional — PATCH one column at a time."""

    subject_id: int | None = None
    subject_name: str | None = None
    topic_name: str | None = None
    difficulty: Difficulty | None = None
    question_type: QuestionType | None = None

    blocks: list[DraftBlock] | None = None
    variants: list[DraftVariant] | None = None

    task_description_ru: str | None = None
    task_description_kk: str | None = None
    question_translation_ru: str | None = None
    question_translation_kk: str | None = None
    explanation_ru: str | None = None
    explanation_kk: str | None = None

    source: DraftSource | None = None
    validation: dict | None = None
    dedup_of_question_id: int | None = None
    status: DraftStatus | None = None
    reviewed_by: str | None = None


class QuestionDraftReadDTO(BaseModel):
    """Full draft as stored, returned to the admin panel."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID | None = None

    subject_id: int | None = None
    subject_name: str | None = None
    topic_name: str | None = None
    difficulty: Difficulty | None = None
    question_type: QuestionType | None = None

    blocks: list[DraftBlock] = Field(default_factory=list)
    variants: list[DraftVariant] = Field(default_factory=list)

    task_description_ru: str | None = None
    task_description_kk: str | None = None
    question_translation_ru: str | None = None
    question_translation_kk: str | None = None
    explanation_ru: str | None = None
    explanation_kk: str | None = None

    source: DraftSource | None = None
    validation: dict | None = None
    status: DraftStatus
    dedup_of_question_id: int | None = None
    published_question_id: int | None = None
    reviewed_by: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None


class QuestionDraftListDTO(BaseModel):
    """Paginated list envelope for `GET /admin/question-drafts`."""

    items: list[QuestionDraftReadDTO]
    total: int
    limit: int
    offset: int
