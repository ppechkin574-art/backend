"""Business logic for the question-draft review pipeline.

CRUD + lifecycle (`publish`, `reject`) on top of `QuestionDraftRepository`.

The headline method is `publish`: it converts a reviewed draft into a
real, live `questions` row by REUSING the existing question create
service — the very same path the XLSX importer uses
(`quiz.services._import.ImportService._create_question`). We do NOT
hand-roll block / variant / text-block-link inserts here; we build a
`QuestionCreateServiceDTO` and hand it to `QuestionService.create`,
which goes through `to_question_create_repo` → the questions UoW and
produces the normalized result (TextBlockLink → TextBlock per
question / per variant). This guarantees published drafts are
byte-for-byte the same shape as admin-authored / imported questions.

Subject / topic resolution mirrors the importer:
- subject: by `subject_id` if given, else `subject_service.get_or_create_by_name`.
- topic:   `topic_service.get_or_create_topic(topic_name, subject_id)` when a name is present.
"""

import logging

from fastapi import HTTPException, status

from quiz.dtos.enums import BlockType, DraftStatus, QuestionType
from quiz.dtos.hint import HintCreateServiceDTO  # noqa: F401  (kept for parity / future hint support)
from quiz.dtos.question_drafts import (
    DraftBlock,
    DraftVariant,
    QuestionDraftCreateDTO,
    QuestionDraftUpdateDTO,
)
from quiz.dtos.questions import QuestionCreateServiceDTO
from quiz.dtos.text_blocks import TextBlockServiceDTO
from quiz.dtos.variants import VariantCreateServiceDTO
from quiz.models.question_drafts import QuestionDraft
from quiz.repositories.question_drafts import QuestionDraftRepository
from quiz.services.questions import QuestionServiceInterface
from quiz.services.subjects import SubjectServiceInterface
from quiz.services.topics import TopicServiceInterface

logger = logging.getLogger(__name__)


class QuestionDraftService:
    def __init__(
        self,
        repo: QuestionDraftRepository,
        question_service: QuestionServiceInterface,
        subject_service: SubjectServiceInterface,
        topic_service: TopicServiceInterface,
    ):
        self.repo = repo
        self.question_service = question_service
        self.subject_service = subject_service
        self.topic_service = topic_service

    # ─── reads ───────────────────────────────────────────────────────

    def list(
        self,
        status: DraftStatus | None = None,
        subject_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QuestionDraft], int]:
        return self.repo.list(
            status=status, subject_id=subject_id, limit=limit, offset=offset
        )

    def get_one(self, draft_id: int) -> QuestionDraft:
        draft = self.repo.get(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Черновик с id={draft_id} не найден",
            )
        return draft

    # ─── writes ──────────────────────────────────────────────────────

    def create(self, payload: QuestionDraftCreateDTO) -> QuestionDraft:
        draft = QuestionDraft(
            subject_id=payload.subject_id,
            subject_name=payload.subject_name,
            topic_name=payload.topic_name,
            difficulty=payload.difficulty,
            question_type=payload.question_type or QuestionType.single_choice,
            blocks=[b.model_dump(mode="json") for b in payload.blocks],
            variants=[v.model_dump(mode="json") for v in payload.variants],
            task_description_ru=payload.task_description_ru,
            task_description_kk=payload.task_description_kk,
            question_translation_ru=payload.question_translation_ru,
            question_translation_kk=payload.question_translation_kk,
            explanation_ru=payload.explanation_ru,
            explanation_kk=payload.explanation_kk,
            source=payload.source.model_dump(mode="json") if payload.source else None,
            validation=payload.validation,
            dedup_of_question_id=payload.dedup_of_question_id,
            status=payload.status or DraftStatus.draft,
        )
        return self.repo.create(draft)

    def update(
        self, draft_id: int, payload: QuestionDraftUpdateDTO
    ) -> QuestionDraft:
        draft = self.get_one(draft_id)
        self._guard_mutable(draft)

        data = payload.model_dump(exclude_unset=True)

        # JSON-ish fields need explicit serialization of nested models.
        if "blocks" in data:
            draft.blocks = (
                [b.model_dump(mode="json") for b in payload.blocks]
                if payload.blocks is not None
                else []
            )
            data.pop("blocks")
        if "variants" in data:
            draft.variants = (
                [v.model_dump(mode="json") for v in payload.variants]
                if payload.variants is not None
                else []
            )
            data.pop("variants")
        if "source" in data:
            draft.source = (
                payload.source.model_dump(mode="json") if payload.source else None
            )
            data.pop("source")

        for field, value in data.items():
            setattr(draft, field, value)

        self.repo.db.flush()
        return draft

    def delete(self, draft_id: int) -> None:
        draft = self.get_one(draft_id)
        self.repo.delete(draft)

    def reject(self, draft_id: int, reviewed_by: str | None = None) -> QuestionDraft:
        draft = self.get_one(draft_id)
        if draft.status == DraftStatus.published:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Опубликованный черновик нельзя отклонить",
            )
        draft.status = DraftStatus.rejected
        if reviewed_by:
            draft.reviewed_by = reviewed_by
        self.repo.db.flush()
        return draft

    # ─── publish ─────────────────────────────────────────────────────

    async def publish(
        self, draft_id: int, reviewed_by: str | None = None
    ) -> QuestionDraft:
        """Map the draft → QuestionCreateServiceDTO → live `questions` row.

        Idempotency: a draft already in `published` state is rejected
        (409) so we never duplicate the live question on a double-click.
        """
        draft = self.get_one(draft_id)

        if draft.status == DraftStatus.published:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Черновик уже опубликован",
            )
        if draft.status == DraftStatus.rejected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Отклонённый черновик нельзя опубликовать",
            )

        subject_id = await self._resolve_subject_id(draft)
        topic_id = await self._resolve_topic_id(draft, subject_id)

        create_dto = QuestionCreateServiceDTO(
            subject_id=subject_id,
            topic_id=topic_id,
            difficulty=draft.difficulty,
            type=draft.question_type or QuestionType.single_choice,
            blocks=self._to_block_dtos(draft.blocks),
            variants=self._to_variant_dtos(draft.variants),
            hint=None,
            task_description_ru=draft.task_description_ru,
            task_description_kk=draft.task_description_kk,
            question_translation_ru=draft.question_translation_ru,
            question_translation_kk=draft.question_translation_kk,
            explanation_ru=draft.explanation_ru,
            explanation_kk=draft.explanation_kk,
        )

        # Reuse the existing create path — it commits its own UoW and
        # builds the normalized question/blocks/variants.
        created_question = self.question_service.create(create_dto)

        draft.status = DraftStatus.published
        draft.published_question_id = created_question.id
        if reviewed_by:
            draft.reviewed_by = reviewed_by
        self.repo.db.flush()

        logger.info(
            "Published draft %s → live question %s", draft.id, created_question.id
        )
        return draft

    # ─── helpers ─────────────────────────────────────────────────────

    def _guard_mutable(self, draft: QuestionDraft) -> None:
        if draft.status == DraftStatus.published:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Опубликованный черновик редактировать нельзя",
            )

    async def _resolve_subject_id(self, draft: QuestionDraft) -> int:
        if draft.subject_id is not None:
            return draft.subject_id
        if draft.subject_name:
            subject = await self.subject_service.get_or_create_by_name(
                draft.subject_name
            )
            return subject.id
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Для публикации нужен subject_id или subject_name",
        )

    async def _resolve_topic_id(
        self, draft: QuestionDraft, subject_id: int
    ) -> int | None:
        if not draft.topic_name:
            return None
        topic = await self.topic_service.get_or_create_topic(
            draft.topic_name, subject_id
        )
        return topic.id

    @staticmethod
    def _to_block_dtos(blocks: list | None) -> list[TextBlockServiceDTO]:
        """Normalize stored JSON blocks → TextBlockServiceDTO list."""
        result: list[TextBlockServiceDTO] = []
        for i, raw in enumerate(blocks or []):
            block = DraftBlock.model_validate(raw)
            result.append(
                TextBlockServiceDTO(
                    id=None,
                    order=block.order if block.order is not None else i,
                    type=block.type or BlockType.text,
                    value=block.value,
                )
            )
        return result

    @classmethod
    def _to_variant_dtos(cls, variants: list | None) -> list[VariantCreateServiceDTO]:
        """Normalize stored JSON variants → VariantCreateServiceDTO list.

        A variant may carry either `blocks` (used directly) or a plain
        `value` (synthesized into a single text block at order 0).
        """
        result: list[VariantCreateServiceDTO] = []
        for raw in variants or []:
            variant = DraftVariant.model_validate(raw)
            if variant.blocks:
                var_blocks = cls._to_block_dtos(
                    [b.model_dump() for b in variant.blocks]
                )
            else:
                var_blocks = [
                    TextBlockServiceDTO(
                        id=None,
                        order=0,
                        type=BlockType.text,
                        value=variant.value or "",
                    )
                ]
            result.append(
                VariantCreateServiceDTO(
                    blocks=var_blocks,
                    is_correct=variant.is_correct,
                    weight=variant.weight,
                )
            )
        return result
