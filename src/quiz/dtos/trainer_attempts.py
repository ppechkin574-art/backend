from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from quiz.dtos.enums import Difficulty, Status, TestType
from quiz.dtos.questions import (
    QuestionServiceDTO,
    QuestionWithAnswerRepositoryDTO,
    QuestionWithAnswerServiceDTO,
)
from quiz.dtos.variants import VariantServiceDTO
from quiz.models.trainer import TrainerAttempt


class TrainerAttemptRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_guid: UUID
    trainer_id: int
    status: Status
    started_at: datetime
    completed_at: datetime | None
    score: int = 0
    questions: list[QuestionWithAnswerRepositoryDTO] | None = None

    @staticmethod
    def custom(ta: TrainerAttempt):
        questions_dto = []
        for ta_question in ta.questions:
            qwa_dto = QuestionWithAnswerRepositoryDTO.custom(ta_question, ta_question.answers)
            if qwa_dto is not None:
                questions_dto.append(qwa_dto)

        return TrainerAttemptRepositoryDTO(
            id=ta.id,
            student_guid=ta.student_guid,
            trainer_id=ta.trainer_id,
            status=ta.status,
            started_at=ta.started_at,
            completed_at=ta.completed_at,
            score=ta.score,
            questions=questions_dto,
        )


class TrainerAttemptServiceDTO(TrainerAttemptRepositoryDTO):
    questions: list[QuestionWithAnswerServiceDTO] = Field(default_factory=list)


class TrainerAttemptCreateRepositoryDTO(BaseModel):
    model_config = ConfigDict(use_enum_values=True, from_attributes=True)

    student_guid: UUID
    trainer_id: int
    status: Status = Field(default=Status.in_progress)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    score: int = Field(default=0)
    completed_at: datetime | None = Field(default=None)


class TrainerAttemptCreateServiceDTO(BaseModel):
    student_guid: UUID
    topic_id: int
    status: Status = Field(default=Status.in_progress)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class TestCreateRepositoryDTO(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    student_id: UUID
    topic_id: int
    difficulty: Difficulty
    type: TestType


class TrainerAttemptQueryRepositoryDTO(BaseModel):
    id: int | None = None


class QuestionResultDTO(BaseModel):
    question_id: int
    is_correct: bool
    chosen_variant_ids: list[int]
    correct_variant_ids: list[int]
    spend_time: float


class FinishAttemptResponseDTO(BaseModel):
    attempt_id: int
    status: Status
    score: int | None = None
    correct_answers: int
    incorrect_answers: int
    max_score: int
    completed_at: datetime | None = None
    question_results: list[QuestionResultDTO] = []
    correct_question_ids: list[int] = []
    incorrect_question_ids: list[int] = []
    total_questions: int = 0
    skipped_answers: int = 0
    total_spend_time: float = 0.0
    average_time_per_question: float = 0.0
    trainer_id: int | None = None
    started_at: datetime | None = None


class AdminAttemptDTO(BaseModel):
    id: int
    user_id: UUID
    user_email: str | None
    topic_name: str
    subject_name: str
    status: Status
    score: float
    max_score: int
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: int | None


class AdminAttemptListDTO(BaseModel):
    attempts: list[AdminAttemptDTO]
    total_count: int
    page: int
    page_size: int


class TrainerAttemptStatisticDTO(BaseModel):
    """DTO для статистики попытки тренажера"""

    attempt_id: int
    score: float
    correct: int
    incorrect: int
    skiped: int
    total_questions: int
    spend_time: int

    @computed_field
    @property
    def correct_percentage(self) -> float:
        if self.total_questions > 0:
            return (self.correct / self.total_questions) * 100
        return 0.0

    @computed_field
    @property
    def completion_rate(self) -> float:
        if self.total_questions > 0:
            answered = self.total_questions - self.skiped
            return (answered / self.total_questions) * 100
        return 0.0

    @computed_field
    @property
    def avg_time_per_question(self) -> float:
        answered = self.total_questions - self.skiped
        if answered > 0:
            return self.spend_time / answered
        return 0.0


class VariantWithAnswerDTO(VariantServiceDTO):
    """Вариант ответа с информацией о правильности и выборе пользователя"""

    user_selected: bool = False


class QuestionWithAnswerDetailDTO(QuestionServiceDTO):
    """Вопрос с ответами пользователя и правильными ответами"""

    question_number: int
    is_correct: bool | None = None
    variants: list[VariantWithAnswerDTO]
    topic_name: str | None = None


class TrainerAttemptDetailDTO(BaseModel):
    """Детальная статистика попытки тренажера"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # guid: UUID
    status: Status
    score: int
    accuracy: float
    started_at: datetime
    completed_at: datetime | None = None
    total_questions: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    partial_correct_answers: int = 0
    spend_time_seconds: int
    trainer_id: int
    trainer_name: str | None = None
    topic_id: int | None = None
    topic_name: str | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    questions: list[QuestionWithAnswerDetailDTO]


class TrainerAttemptResultDTO(BaseModel):
    attempt_id: int
    trainer_id: int
    started_at: datetime
    completed_at: datetime | None = None
    score: int
    correct_answers: int
    incorrect_answers: int
    max_score: int
    reward_for_attempt: int = 1  # temp
    # reward_for_time: int = 2  # temp


class TrainerAttemptPublicDTO(BaseModel):
    id: int
    student_guid: UUID
    trainer_id: int
    status: Status
    started_at: datetime
    completed_at: datetime | None = None
    score: int = 0
    questions: list[dict]


class TrainerAttemptAnswerResponseDTO(BaseModel):
    trainer_attempt_question_id: int
    answered_variants: list[int]
    is_correct: bool
    correct_variants: list[int]
    is_completed: bool
    total_questions: int
    answered_questions: int
    attempt_id: int
