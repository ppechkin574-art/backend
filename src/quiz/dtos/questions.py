from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quiz.dtos.enums import Difficulty, QuestionType
from quiz.dtos.hint import (
    HintCreateRepositoryDTO,
    HintCreateServiceDTO,
    HintRepositoryDTO,
    HintServiceDTO,
    HintUpdateRepositoryDTO,
    HintUpdateServiceDTO,
)
from quiz.dtos.text_blocks import (
    TextBlockRepositoryDTO,
    TextBlockServiceDTO,
)
from quiz.dtos.trainer_attempt_answers import (
    TrainerAttemptAnswerRepositoryDTO,
    TrainerAttemptAnswerServiceDTO,
)
from quiz.dtos.variants import (
    ImportVariantCreateDTO,
    VariantCreateRepositoryDTO,
    VariantCreateServiceDTO,
    VariantRepositoryDTO,
    VariantServiceDTO,
    VariantUpdateRepositoryDTO,
    VariantUpdateServiceDTO,
)

if TYPE_CHECKING:
    from quiz.models.trainer import TrainerAttemptAnswer, TrainerAttemptQuestion


class QuestionRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID | None
    topic_id: int | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    topic_name: str | None = None
    difficulty: Difficulty | None = None
    type: QuestionType | None
    blocks: list[TextBlockRepositoryDTO]
    hint: HintRepositoryDTO | None = None
    variants: list[VariantRepositoryDTO] | None = None

    @staticmethod
    def custom(question) -> QuestionRepositoryDTO:
        if isinstance(question, QuestionRepositoryDTO):
            return question
        if hasattr(question, "trainer_attempt_question_id"):
            return question
        if hasattr(question, "model_config"):
            return question
        question_blocks = []
        if question.link and question.link.blocks:
            question_blocks = [
                TextBlockRepositoryDTO.model_validate(b) for b in sorted(question.link.blocks, key=lambda x: x.order)
            ]
        if isinstance(question, QuestionRepositoryDTO):
            return question

        if hasattr(question, "trainer_attempt_question_id"):
            return question

        if hasattr(question, "model_config"):
            return question
        question_blocks = []
        if question.link and question.link.blocks:
            question_blocks = [
                TextBlockRepositoryDTO.model_validate(b) for b in sorted(question.link.blocks, key=lambda x: x.order)
            ]
        hint_dto = None
        if question.hint and question.hint.link and question.hint.link.blocks:
            hint_blocks = [
                TextBlockRepositoryDTO.model_validate(b)
                for b in sorted(question.hint.link.blocks, key=lambda x: x.order)
            ]
            hint_dto = HintRepositoryDTO(id=question.hint.id, guid=question.hint.guid, blocks=hint_blocks)
        variants_dto = []
        if question.variants:
            for variant in question.variants:
                variant_blocks = []
                if variant.link and variant.link.blocks:
                    variant_blocks = [
                        TextBlockRepositoryDTO.model_validate(b)
                        for b in sorted(variant.link.blocks, key=lambda x: x.order)
                    ]
                variants_dto.append(
                    VariantRepositoryDTO(
                        id=variant.id,
                        guid=variant.guid,
                        question_id=variant.question_id,
                        blocks=variant_blocks,
                        is_correct=variant.is_correct,
                        weight=variant.weight,
                    )
                )
        return QuestionRepositoryDTO(
            id=question.id,
            guid=question.guid,
            topic_id=question.topic_id,
            subject_id=question.subject_id,
            subject_name=question.subject.name if question.subject else None,
            topic_name=question.topic.name if question.topic else None,
            difficulty=question.difficulty,
            type=question.question_type,
            blocks=question_blocks,
            hint=hint_dto,
            variants=variants_dto,
        )


class QuestionWithAnswerRepositoryDTO(QuestionRepositoryDTO):
    trainer_attempt_question_id: int
    answers: list[TrainerAttemptAnswerRepositoryDTO] | None

    @staticmethod
    def custom(
        ta_question: TrainerAttemptQuestion, answers: list[TrainerAttemptAnswer]
    ) -> QuestionWithAnswerRepositoryDTO | None:
        question = ta_question.question
        if question is None:
            return None

        return QuestionWithAnswerRepositoryDTO(
            trainer_attempt_question_id=ta_question.id,
            id=question.id,
            guid=question.guid,
            type=question.question_type,
            topic_id=question.topic_id,
            subject_id=question.subject_id,
            difficulty=question.difficulty,
            hint=HintRepositoryDTO.custom(question.hint) if question.hint else None,
            variants=([VariantRepositoryDTO.custom(v) for v in question.variants] if question.variants else []),
            blocks=[TextBlockRepositoryDTO.model_validate(b) for b in question.link.blocks],
            answers=([TrainerAttemptAnswerRepositoryDTO.model_validate(a) for a in answers] if answers else []),
        )


class QuestionServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID | None = None
    topic_id: int | None = None
    topic_name: str | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    difficulty: Difficulty | None = None
    type: QuestionType | None = None
    blocks: list[TextBlockServiceDTO]
    hint: HintServiceDTO | None = None
    variants: list[VariantServiceDTO]


class QuestionWithAnswerServiceDTO(QuestionServiceDTO):
    trainer_attempt_question_id: int
    answers: list[TrainerAttemptAnswerServiceDTO] | None = None


class QuestionUpdateRepositoryDTO(BaseModel):
    topic_id: int | None = None
    difficulty: Difficulty | None = None
    subject_id: int | None = None
    type: QuestionType | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    hint: HintUpdateRepositoryDTO | None = None
    variants: list[VariantUpdateRepositoryDTO] | None = None


class QuestionUpdateServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    topic_id: int | None = None
    difficulty: Difficulty | None = None
    subject_id: int | None = None
    type: QuestionType | None = None
    blocks: list[TextBlockServiceDTO] | None = None
    blocks: list[TextBlockServiceDTO] | None = None
    hint: HintUpdateServiceDTO | None = None
    variants: list[VariantUpdateServiceDTO] | None = None


class QuestionQueryRepositoryDTO(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    student_id: UUID | None = None
    topic_id: int | None = None
    blocks: list[TextBlockRepositoryDTO] | None = None
    subject_id: int | None = None
    difficulty: Difficulty | None = None
    answered: bool | None = None
    type: QuestionType | None = None


class QuestionCreateRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topic_id: int | None = None
    subject_id: int
    # ent_option_id: int | None = None
    difficulty: Difficulty | None = None
    type: QuestionType
    blocks: list[TextBlockRepositoryDTO] | None = None
    variants: list[VariantCreateRepositoryDTO]
    hint: HintCreateRepositoryDTO | None = None


class QuestionCreateServiceDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    topic_id: int | None = None
    subject_id: int
    ent_option_id: int | None = None
    difficulty: Difficulty | None = None
    type: QuestionType
    blocks: list[TextBlockServiceDTO] | None = None
    variants: list[VariantCreateServiceDTO]
    hint: HintCreateServiceDTO | None = None


class ImportQuestionCreateDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    subject: str
    type: QuestionType = QuestionType.single_choice
    question_blocks: list[TextBlockServiceDTO]
    answers: list[ImportVariantCreateDTO]
    topic_name: str | None = None
    difficulty: Difficulty | None = None
    hint_blocks: list[TextBlockServiceDTO] | None = None
    ent_option_number: int | None = None


class ImportQuestionsDTO(BaseModel):
    questions: list[ImportQuestionCreateDTO]
    subject_id: int
    topic_id: int | None = None
    difficulty: Difficulty | None = None


class QuestionsStatsDTO(BaseModel):
    total_questions: int
    questions_in_trainers: int
    questions_in_ent_options: int
    questions_by_subject: list[dict]
    questions_by_topic: list[dict]
