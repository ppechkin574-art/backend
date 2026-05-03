import logging
from datetime import date
from typing import Any, TypeVar

from fastapi import Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quiz.dtos.enums import QuestionType, SubjectType
from quiz.dtos.questions import Difficulty
from quiz.dtos.text_blocks import TextBlockServiceDTO

logger = logging.getLogger(__name__)

T = TypeVar("T")


class QuizAnswerRequestDTO(BaseModel):
    variants: list[int] = Field(..., min_length=1, description="Должен быть выбран хотя бы один вариант")
    spend_time: int

    @field_validator("variants")
    @classmethod
    def validate_variants(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Необходимо выбрать хотя бы один вариант ответа")
        return v


class QuizCreateRequestDTO(BaseModel):
    topic_id: int


class SubjectCreateRequestDTO(BaseModel):
    name: str
    type: SubjectType
    image: str | None = ""
    description: str | None = None


class SubjectUpdateRequestDTO(BaseModel):
    name: str
    type: SubjectType | None = None
    image: str | None = None
    description: str | None = None


class TopicCreateRequestDTO(BaseModel):
    name: str
    subject_id: int


class TopicUpdateRequestDTO(BaseModel):
    name: str
    subject_id: int


class VariantCreateRequestDTO(BaseModel):
    blocks: list[TextBlockServiceDTO]
    is_correct: bool


class HintCreateRequestDTO(BaseModel):
    blocks: list[TextBlockServiceDTO] | None = None


class QuestionCreateRequestDTO(BaseModel):
    subject_id: int
    topic_id: int | None = None
    difficulty: Difficulty
    type: QuestionType
    blocks: list[TextBlockServiceDTO]
    variants: list[VariantCreateRequestDTO]
    hint: HintCreateRequestDTO


class QuestionListQueryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Query(0, ge=0, description="Начальная позиция")
    length: int = Query(10, ge=1, description="Количество элементов")
    draw: int = Query(1, ge=1, description="Номер запроса для DataTables")
    search: str = Query("", description="Поисковая строка")
    order: str = Query(
        '"[{"column": "id", "dir": "asc"}]"',
        description="Порядок сортировки в формате JSON",
    )

    difficulty: str | None = Query(None, description="Фильтр по сложности (через запятую)")
    question_type: str | None = Query(None, description="Фильтр по типу вопроса (через запятую)")
    subject_ids: str | None = Query(None, description="Фильтр по ID предметов (через запятую)")
    topic_ids: str | None = Query(None, description="Фильтр по ID тем (через запятую)")
    usage_type: str | None = Query(None, description="Фильтр по типу использования")

    @property
    def page(self) -> int:
        """Вычисляет номер страницы из start и length"""
        return (self.start // self.length) + 1 if self.length else 1

    @property
    def page_size(self) -> int:
        """Алиас для length для совместимости с сервисом"""
        return self.length

    @property
    def sort_columns(self) -> list[str]:
        """Извлекает колонки для сортировки из order"""
        import json

        try:
            orders = json.loads(self.order[1:-1])
            if isinstance(orders, list):
                return [item.get("column", "id") for item in orders]
        except Exception as e:
            logger.warning("Something happened: %s", e)
        return ["id"]

    @property
    def is_sort_ascendings(self) -> list[bool]:
        """Извлекает направление сортировки из order"""
        import json

        try:
            orders = json.loads(self.order[1:-1])
            if isinstance(orders, list):
                return [item.get("dir", "asc") == "asc" for item in orders]
        except Exception as e:
            logger.warning("Something happened: %s", e)
        return [True]

    def get_subject_ids_list(self) -> list[int] | None:
        """Преобразует строку subject_ids в список int"""
        if not self.subject_ids:
            return None
        try:
            return [int(item.strip()) for item in self.subject_ids.split(",") if item.strip()]
        except (ValueError, TypeError):
            return None

    def get_topic_ids_list(self) -> list[int] | None:
        """Преобразует строку topic_ids в список int"""
        if not self.topic_ids:
            return None
        try:
            return [int(item.strip()) for item in self.topic_ids.split(",") if item.strip()]
        except (ValueError, TypeError):
            return None

    def get_difficulty_list(self) -> list[Difficulty] | None:
        """Преобразует строку difficulty в список Difficulty"""
        if not self.difficulty:
            return None
        try:
            return [Difficulty(item.strip()) for item in self.difficulty.split(",") if item.strip()]
        except (ValueError, TypeError):
            return None

    def get_question_type_list(self) -> list[QuestionType] | None:
        """Преобразует строку question_type в список QuestionType"""
        if not self.question_type:
            return None
        try:
            return [QuestionType(item.strip()) for item in self.question_type.split(",") if item.strip()]
        except (ValueError, TypeError):
            return None


class VariantUpdateRequestDTO(BaseModel):
    blocks: list[TextBlockServiceDTO] | None = None
    is_correct: bool | None = None


class HintUpdateRequestDTO(BaseModel):
    blocks: list[TextBlockServiceDTO] | None = None


class QuestionUpdateRequestDTO(BaseModel):
    subject_id: int | None = None
    topic_id: int | None = None
    difficulty: Difficulty | None = None
    type: QuestionType | None = None
    blocks: list[TextBlockServiceDTO] | None = None
    hint: HintUpdateRequestDTO | None = None
    variants: list[VariantUpdateRequestDTO] | None = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class ImportQuestionsRequestDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    type: QuestionType
    file: UploadFile


class StatisticsPeriodRequestDTO(BaseModel):
    date_start: date
    date_end: date


class TopicStatisticsRequestDTO(BaseModel):
    topic_id: int
    date_start: date
    date_end: date


class EntStatisticsRequestDTO(BaseModel):
    date_start: date
    date_end: date


class EntQuestionAnswerRequestDTO(BaseModel):
    question_id: int
    variants: list[int]


class EntAttemptAnswerRequestDTO(BaseModel):
    ent_attempt_id: int
    questions: list[EntQuestionAnswerRequestDTO]


class EntOptionsFilterRequestDTO(BaseModel):
    subject_id: int | None = None


class StartAttemptRequestDTO(BaseModel):
    ent_option_id: int


class StartFullExamRequestDTO(BaseModel):
    """DTO для создания полноценного экзамена из 4 предметов"""

    subject_combination_id: int  # Связка профильных предметов


class TrainerCreateRequestDTO(BaseModel):
    name: str
    topic_id: int


class TrainerUpdateRequestDTO(BaseModel):
    name: str | None = None
    topic_id: int | None = None


class EntOptionCreateRequestDTO(BaseModel):
    subject_id: int
    option_number: int | None = None


class EntOptionUpdateRequestDTO(BaseModel):
    subject_id: int | None = None
    year: int | None = None
    subject: str | None = None
    question_count: int | None = None


class MergeSubjectsRequestDTO(BaseModel):
    source_subject_id: int
    target_subject_id: int


class MergeTopicsRequestDTO(BaseModel):
    source_topic_id: int
    target_topic_id: int


class SuccessResponseDTO(BaseModel):
    message: str


class DeleteResponseDTO(SuccessResponseDTO):
    pass


class ListResponseDTO[T](BaseModel):
    data: list[T]
    total_count: int
    count: int


class ImportResponseDTO(BaseModel):
    created: int
    errors: list[str]
    total_processed: int


class QuizAnswerResponseDTO(BaseModel):
    trainer_attempt_question_id: int
    answered_variants: list[int]
    is_completed: bool = False
    total_questions: int = 0
    answered_questions: int = 0
    attempt_id: int


class TrainerInfoResponseDTO(BaseModel):
    id: int
    name: str
    question_count: int
    completed_question_indexes: list[int] = Field(default_factory=list)


class TrainerWithProgressDTO(BaseModel):
    id: int
    name: str
    question_count: int
    completed_question_indexes: list[int]
    progress: float

    class Config:
        from_attributes = True


class TopicWithTrainersDTO(BaseModel):
    id: int
    name: str
    subject_id: int
    trainers: list[TrainerWithProgressDTO]


class TopicWithTrainersResponseDTO(BaseModel):
    count: int
    data: list[TopicWithTrainersDTO]


class SubjectStatsResponseDTO(BaseModel):
    subject_id: int
    topic_count: int
    question_count: int


class TopicStatsResponseDTO(BaseModel):
    topic_id: int
    topic_name: str
    subject_id: int
    question_count: int


class MergeResponseDTO(BaseModel):
    message: str
    merged_entity: dict
    source_id: int
    target_id: int


class QuestionListResponseDTO(ListResponseDTO[Any]):
    pass


class SubjectWithQuestionsResponseDTO(BaseModel):
    subject: Any
    questions: QuestionListResponseDTO


class TopicWithQuestionsResponseDTO(BaseModel):
    topic: Any
    questions: QuestionListResponseDTO


QuizAnswerDTO = QuizAnswerRequestDTO
QuizCreateDTO = QuizCreateRequestDTO
SubjectCreateDTO = SubjectCreateRequestDTO
SubjectUpdateDTO = SubjectUpdateRequestDTO
TopicCreateDTO = TopicCreateRequestDTO
TopicUpdateDTO = TopicUpdateRequestDTO
VariantCreateDTO = VariantCreateRequestDTO
HintCreateDTO = HintCreateRequestDTO
QuestionCreateDTO = QuestionCreateRequestDTO
VariantUpdateDTO = VariantUpdateRequestDTO
HintUpdateDTO = HintUpdateRequestDTO
QuestionUpdateDTO = QuestionUpdateRequestDTO
ImportQuestionsFormDTO = ImportQuestionsRequestDTO
TopicStatisticGetDTO = TopicStatisticsRequestDTO
EntStatisticGetDTO = EntStatisticsRequestDTO
EntQuestionAnswerDTO = EntQuestionAnswerRequestDTO
EntAttemptAnswerDTO = EntAttemptAnswerRequestDTO
OptionsGetDTO = EntOptionsFilterRequestDTO
StartAttemptDTO = StartAttemptRequestDTO
TrainerInfoDTO = TrainerInfoResponseDTO


# Subject Combinations DTOs
class SubjectCombinationResponseDTO(BaseModel):
    """DTO для ответа со связкой предметов"""

    id: int
    name: str
    description: str | None = None
    specialized_subject_1_id: int
    specialized_subject_1_name: str
    specialized_subject_2_id: int
    specialized_subject_2_name: str


class SubjectCombinationCreateRequestDTO(BaseModel):
    """DTO для создания связки предметов"""

    name: str = Field(..., min_length=1, max_length=255, description="Название связки")
    description: str | None = Field(None, max_length=1000, description="Описание связки")
    specialized_subject_1_id: int = Field(..., gt=0, description="ID первого профильного предмета")
    specialized_subject_2_id: int = Field(..., gt=0, description="ID второго профильного предмета")


class SubjectCombinationUpdateRequestDTO(BaseModel):
    """DTO для обновления связки предметов"""

    name: str | None = Field(None, min_length=1, max_length=255, description="Название связки")
    description: str | None = Field(None, max_length=1000, description="Описание связки")
    specialized_subject_1_id: int | None = Field(None, gt=0, description="ID первого профильного предмета")
    specialized_subject_2_id: int | None = Field(None, gt=0, description="ID второго профильного предмета")


class ImageResponse(BaseModel):
    image_url: str
