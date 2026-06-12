from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from quiz.dtos.enums import ExamType, Status
from quiz.dtos.questions import QuestionServiceDTO
from quiz.dtos.variants import VariantServiceDTO


class EntAttemptDetailDTO(BaseModel):
    attempt_id: int
    option_number: int
    completed_at: datetime
    correct_answers: int
    total_questions: int
    spend_time: int
    score: float

    @computed_field
    @property
    def correct_percentage(self) -> float:
        if self.total_questions > 0:
            return (self.correct_answers / self.total_questions) * 100
        return 0.0

    @computed_field
    @property
    def avg_time_per_question(self) -> float:
        if self.total_questions > 0:
            return self.spend_time / self.total_questions
        return 0.0


class EntAttemptOptionStatisticRepositoryDTO(BaseModel):
    attempt_id: int
    score: int
    skiped: int
    correct: int
    partial_correct: int
    incorrect: int
    spend_time: int


class EntAttemptOptionStatisticServiceDTO(BaseModel):
    attempt_id: int
    score: int
    skiped: int
    correct: int
    partial_correct: int
    incorrect: int
    spend_time: int


class EntAttemptCreateServiceDTO(BaseModel):
    student_guid: UUID
    ent_option_id: int | None = None
    status: Status = Field(default=Status.in_progress)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deadline_at: datetime | None = None
    duration_seconds: int | None = None
    score: int | None = None
    exam_type: ExamType = Field(default=ExamType.by_subject)
    subject_combination_id: int | None = None
    current_question_index: int = 0
    full_exam_question_ids: str | None = None


class EntAttemptCreateRepositoryDTO(BaseModel):
    student_guid: UUID
    ent_option_id: int | None = None
    status: Status = Field(default=Status.in_progress)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deadline_at: datetime | None = None
    duration_seconds: int | None = None
    score: int | None = None
    exam_type: ExamType = Field(default=ExamType.by_subject)
    subject_combination_id: int | None = None
    current_question_index: int = 0
    full_exam_question_ids: str | None = None


class EntAttemptRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    ent_option_id: int | None
    student_guid: UUID
    status: Status = Field(default=Status.in_progress)
    score: int = 0
    started_at: datetime
    deadline_at: datetime | None
    completed_at: datetime | None
    exam_type: ExamType = Field(default=ExamType.by_subject)
    subject_combination_id: int | None = None
    current_question_index: int = 0
    full_exam_question_ids: str | None = None
    points_awarded: bool = False


class SubjectQuestionsDTO(BaseModel):
    """Группа вопросов по предмету для полноценного экзамена"""

    subject_id: int
    subject_name: str
    questions: list[QuestionServiceDTO]


class EntAttemptServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    guid: UUID
    id: int
    ent_option_id: int | None
    question_count: int
    student_guid: UUID
    status: Status = Field(default=Status.in_progress)
    score: int
    started_at: datetime
    deadline_at: datetime
    completed_at: datetime | None
    exam_type: ExamType = Field(default=ExamType.by_subject)
    subject_combination_id: int | None = None
    current_question_index: int = 0
    full_exam_question_ids: str | None = None
    questions: list[QuestionServiceDTO] | list[SubjectQuestionsDTO]


class EntAttemptStatisticRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ent_attempt_id: int
    score: int
    total_questions: int | None = None
    correct: int
    partial_correct: int
    incorrect: int
    skiped: int
    spend_time: int


class EntAttemptStatisticServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ent_attempt_id: int
    score: int
    correct: int
    partial_correct: int
    incorrect: int
    skiped: int
    spend_time: int
    deadline_exceeded: bool = False
    completed_at: datetime
    actual_duration_seconds: int
    allowed_duration_seconds: int


class AdminListQueryDTO(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    search: str | None = None
    sort_by: str | None = None
    sort_order: str | None = "asc"


class BaseEntAttemptHistoryDTO(BaseModel):
    """Базовая информация о попытке для списка истории"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    exam_type: ExamType
    status: Status
    score: int
    started_at: datetime
    completed_at: datetime | None = None
    deadline_at: datetime | None = None
    total_questions: int | None = None
    correct_answers: int | None = None
    incorrect_answers: int | None = None
    skipped_answers: int | None = None
    spend_time_seconds: int | None = None


class EntAttemptBySubjectHistoryDTO(BaseEntAttemptHistoryDTO):
    """Попытка экзамена по одному предмету"""

    exam_type: ExamType = ExamType.by_subject
    ent_option_id: int
    subject_id: int
    subject_name: str
    option_number: int


class EntAttemptFullExamHistoryDTO(BaseEntAttemptHistoryDTO):
    """Попытка полноценного экзамена"""

    exam_type: ExamType = ExamType.full_exam
    subject_combination_id: int
    subject_combination_name: str


EntAttemptHistoryItemDTO = EntAttemptBySubjectHistoryDTO | EntAttemptFullExamHistoryDTO


class VariantWithAnswerDTO(VariantServiceDTO):
    """Вариант ответа с информацией о правильности и выборе пользователя"""

    user_selected: bool = False


class QuestionWithAnswerDTO(QuestionServiceDTO):
    """Вопрос с ответами пользователя и правильными ответами"""

    question_number: int
    is_correct: bool | None = None
    variants: list[VariantWithAnswerDTO]
    subject_name: str | None = None
    topic_name: str | None = None


class SubjectQuestionsWithAnswersDTO(BaseModel):
    """Группа вопросов по предмету с ответами"""

    subject_id: int
    subject_name: str
    questions: list[QuestionWithAnswerDTO]


class UpdateQuestionIndexResponseDTO(BaseModel):
    """Ответ при обновлении позиции вопроса"""

    attempt_id: int
    current_question_index: int
    status: Literal["success"]


class BaseEntAttemptDetailDTO(BaseModel):
    """Базовая детальная информация о попытке"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    exam_type: ExamType
    status: Status
    score: int
    started_at: datetime
    completed_at: datetime | None = None
    deadline_at: datetime | None = None
    total_questions: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    partial_correct_answers: int
    spend_time_seconds: int


class EntAttemptBySubjectDetailDTO(BaseEntAttemptDetailDTO):
    """Детальная информация о попытке экзамена по одному предмету"""

    exam_type: ExamType
    ent_option_id: int
    subject_id: int
    subject_name: str
    option_number: int
    questions: list[QuestionWithAnswerDTO]


class EntAttemptFullExamDetailDTO(BaseEntAttemptDetailDTO):
    """Детальная информация о попытке полноценного экзамена"""

    exam_type: ExamType
    subject_combination_id: int
    subject_combination_name: str
    questions: list[SubjectQuestionsWithAnswersDTO]


EntAttemptDetailWithAnswersDTO = EntAttemptBySubjectDetailDTO | EntAttemptFullExamDetailDTO


class AdminAttemptFilterDTO(BaseModel):
    user_id: UUID | None = None
    topic_id: int | None = None
    subject_id: int | None = None
    status: Status | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
