from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quiz.dtos.questions import QuestionServiceDTO
from quiz.dtos.variants import VariantServiceDTO


# Subject Preferences DTOs
class SubjectPreferenceDTO(BaseModel):
    """Предмет, выбранный для ежедневных тестов"""

    model_config = ConfigDict(from_attributes=True)

    subject_id: int
    subject_name: str
    image: str | None = None
    is_default: bool


class SubjectPreferencesResponseDTO(BaseModel):
    """Ответ с выбранными предметами"""

    subjects: list[SubjectPreferenceDTO]
    can_add_more: bool  # Может ли добавить еще предметы (максимум 5)


class UpdateSubjectPreferencesDTO(BaseModel):
    """Запрос на обновление выбранных предметов"""

    subject_ids: list[int] = Field(..., min_length=2, max_length=5, description="ID предметов (минимум 2, максимум 5)")


# Daily Test DTOs
class DailyTestAttemptDTO(BaseModel):
    """Попытка прохождения ежедневного теста"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    test_date: date
    status: str  # in_progress, completed
    score: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    started_at: datetime
    completed_at: datetime | None
    total_questions: int
    subject_id: int | None = None
    subject_name: str | None = None
    questions: list[QuestionServiceDTO]


class DailyTestHistoryItemDTO(BaseModel):
    """Краткая информация о попытке для истории"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    test_date: date
    subject_id: int | None = None
    subject_name: str | None = None
    status: str
    score: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    total_questions: int
    completed_at: datetime | None


class DailyTestAnswerQuestionDTO(BaseModel):
    """Ответ пользователя на конкретный вопрос"""

    question_id: int
    variants: list[int]


class DailyTestAnswerRequestDTO(BaseModel):
    """Запрос на отправку ответов на ежедневный тест"""

    attempt_id: int
    questions: list[DailyTestAnswerQuestionDTO]


class DailyTestResultDTO(BaseModel):
    """Результат прохождения ежедневного теста"""

    model_config = ConfigDict(from_attributes=True)

    attempt_id: int
    test_date: date
    score: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    total_questions: int
    percentage: float
    completed_at: datetime
    subject_id: int | None = None
    subject_name: str | None = None


class VariantWithAnswerDetailDTO(VariantServiceDTO):
    """Вариант ответа с информацией о правильности и выборе пользователя"""

    user_selected: bool = False


class QuestionWithAnswerDetailDTO(QuestionServiceDTO):
    """Вопрос с детальной информацией об ответах"""

    question_number: int
    is_correct: bool | None = None
    variants: list[VariantWithAnswerDetailDTO]
    subject_name: str | None = None
    topic_name: str | None = None


class DailyTestAttemptDetailDTO(BaseModel):
    """Детальная информация о попытке с ответами"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    test_date: date
    status: str
    score: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    total_questions: int
    started_at: datetime
    completed_at: datetime | None
    percentage: float
    subject_id: int | None = None
    subject_name: str | None = None
    questions: list[QuestionWithAnswerDetailDTO]


# Repository DTOs
class DailyTestAttemptCreateRepositoryDTO(BaseModel):
    """DTO для создания попытки в репозитории"""

    student_guid: UUID
    test_date: date
    status: str = "in_progress"
    subject_id: int | None = None


class DailyTestAttemptRepositoryDTO(BaseModel):
    """DTO попытки из репозитория"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    student_guid: UUID
    test_date: date
    status: str
    score: int
    correct_answers: int
    incorrect_answers: int
    skipped_answers: int
    started_at: datetime
    completed_at: datetime | None
    subject_id: int | None = None


class DailyTestTodayRequestDTO(BaseModel):
    """Доп. DTO для запроса сегодняшнего теста"""

    subject_id: int | None = None


# Device token DTOs
class RegisterDailyTestDeviceTokenDTO(BaseModel):
    """Запрос на регистрацию FCM токена устройства"""

    token: str = Field(..., min_length=1, max_length=512)
    platform: str | None = Field(default=None, max_length=50)
    device_id: str | None = Field(default=None, max_length=255)


class DailyTestDeviceTokenDTO(BaseModel):
    """Информация о сохраненном FCM токене"""

    id: int
    student_guid: UUID
    token: str
    platform: str | None
    device_id: str | None
    created_at: datetime
    updated_at: datetime
