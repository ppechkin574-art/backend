from datetime import date, datetime
from enum import Enum, StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator

from quiz.dtos.enums import ExamType


class ScreenTimeDailyDTO(BaseModel):
    """Экранное время за день"""

    date: str
    screen_time_seconds: int
    screen_time_formatted: str


# ==================== ENUMS ====================


class StatisticPeriod(StrEnum):
    """Период статистики"""

    WEEK = "week"
    MONTH = "month"


class StatisticPeriodType(StrEnum):
    """Типы периодов для статистики"""

    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    CALENDAR_WEEK = "calendar_week"
    CALENDAR_MONTH = "calendar_month"
    CUSTOM = "custom"


# ==================== REQUESTS ====================


class StatisticRequestDTO(BaseModel):
    """Запрос статистики с разными типами периодов"""

    period_type: StatisticPeriodType = Field(
        default=StatisticPeriodType.LAST_7_DAYS,
        description="Тип периода для статистики",
    )

    week_date: date | None = Field(
        default=None, description="Дата для определения календарной недели"
    )

    month_year: str | None = Field(
        default=None, description="Год и месяц в формате 'YYYY-MM'"
    )

    custom_start_date: date | None = Field(
        default=None, description="Начальная дата для произвольного периода"
    )
    custom_end_date: date | None = Field(
        default=None, description="Конечная дата для произвольного периода"
    )

    subject_id: int | None = Field(
        default=None, description="ID предмета для фильтрации статистики тренажеров"
    )

    exam_type: ExamType | None = Field(
        default=ExamType.by_subject, description="Тип экзамена ЕНТ"
    )
    user_id: UUID | None = None


class TopicStatisticGetServiceDTO(BaseModel):
    """DTO для запроса статистики тренажеров"""

    student_guid: UUID
    topic_id: int
    ts_start: int
    ts_end: int


class EntStatisticGetServiceDTO(BaseModel):
    """DTO для запроса статистики ЕНТ"""

    student_guid: UUID
    ts_start: int
    ts_end: int
    exam_type: ExamType = ExamType.by_subject


class ActivityLevel(Enum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ==================== PROGRESS DTOs ====================


class SubjectProgressDTO(BaseModel):
    """Прогресс по предмету"""

    subject_id: int
    subject_name: str
    total_questions: int
    correct_answers: int
    accuracy: float

    @property
    def percentage(self) -> float:
        return round(
            (
                (self.correct_answers / self.total_questions * 100)
                if self.total_questions > 0
                else 0
            ),
            2,
        )


class TopicProgressDTO(BaseModel):
    """Прогресс по теме"""

    topic_id: int
    topic_name: str
    subject_id: int
    subject_name: str
    total_questions: int
    correct_answers: int
    accuracy: float

    @property
    def percentage(self) -> float:
        return round(
            (
                (self.correct_answers / self.total_questions * 100)
                if self.total_questions > 0
                else 0
            ),
            2,
        )


class TopicProgressWithSubjectDTO(TopicProgressDTO):
    """Прогресс по теме с информацией о предмете"""

    pass


# ==================== ENT DTOs ====================


class EntAttemptDetailDTO(BaseModel):
    """Детальная информация по одной попытке ЕНТ"""

    attempt_id: int
    option_number: int
    completed_at: datetime | None
    correct_answers: int
    total_questions: int
    spend_time: int
    score: float
    correct_percentage: float
    avg_time_per_question: float
    median_time_per_question: float = 0.0


class EntStatisticOverallDTO(BaseModel):
    """Агрегированные данные ЕНТ за весь период"""

    total_attempts: int
    total_correct_answers: int
    total_questions: int
    total_spend_time: int
    avg_correct_percentage: float
    overall_avg_time_per_question: float
    median_time_per_question: float
    avg_score: float
    avg_spend_time: float


class EntStatisticDailyDTO(BaseModel):
    """Статистика ЕНТ за один день"""

    date: date
    total_attempts: int
    total_correct_answers: int
    total_questions: int
    total_spend_time: int
    avg_correct_percentage: float
    overall_avg_time_per_question: float
    median_time_per_question: float
    avg_score: float = 0.0
    avg_spend_time: float = 0.0


class EntStatisticServiceDTO(BaseModel):
    """Полная статистика ЕНТ"""

    overall: EntStatisticOverallDTO
    streak: int = 0
    daily: list[EntStatisticDailyDTO]
    attempts: list[EntAttemptDetailDTO]
    exam_type: ExamType = ExamType.by_subject


class EntStatisticSummaryDTO(BaseModel):
    """Сводная статистика по ЕНТ"""

    period_attempts_count: int
    period_total_questions: int = Field(default=0, description="Вопросов за период")
    period_correct_answers: int = Field(
        default=0, description="Правильных ответов за период"
    )
    period_accuracy: float = Field(default=0.0, description="Точность за период")

    overall_total_questions: int = Field(
        default=0, description="Всего вопросов за всё время"
    )
    overall_correct_answers: int = Field(
        default=0, description="Всего правильных ответов за всё время"
    )
    overall_accuracy: float = Field(
        default=0.0, description="Общая точность за всё время"
    )
    overall_average_score: float = Field(
        default=0.0, description="Средний балл за все попытки"
    )

    period_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Прогресс по предметам за период"
    )
    overall_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Общий прогресс по предметам за всё время"
    )
    current_streak: int = Field(default=0, ge=0)
    total_spend_time_seconds: int = Field(
        default=0, description="Общее время, затраченное на ENT тесты (в секундах)"
    )
    total_spend_time_formatted: str = Field(
        default="0s", description="Форматированное время ENT тестов"
    )
    exam_type: str | None = Field(default=None, description="Тип экзамена")


class EntStatisticDTO(BaseModel):
    """Разделенная статистика ENT"""

    by_subject: EntStatisticSummaryDTO
    full_exam: EntStatisticSummaryDTO
    # combined: Optional[EntStatisticSummaryDTO] = None


# ==================== TRAINER DTOs ====================


class TopicAttemptDetailDTO(BaseModel):
    """Детальная информация по одной попытке тренажера"""

    attempt_id: int
    trainer_name: str
    completed_at: datetime | None
    correct_answers: int
    total_questions: int
    spend_time: int
    score: float
    median_time_per_question: float = 0.0

    @property
    def correct_percentage(self) -> float:
        if self.total_questions > 0:
            return (self.correct_answers / self.total_questions) * 100
        return 0.0

    @property
    def avg_time_per_question(self) -> float:
        if self.total_questions > 0:
            return self.spend_time / self.total_questions
        return 0.0


class TopicStatisticOverallDTO(BaseModel):
    """Агрегированные данные тренажеров за весь период"""

    total_attempts: int
    total_correct_answers: int
    total_questions: int
    total_spend_time: int
    avg_correct_percentage: float
    overall_avg_time_per_question: float
    median_time_per_question: float
    avg_score: float
    avg_spend_time: float


class TopicStatisticDailyDTO(BaseModel):
    """Статистика тренажеров за один день"""

    date: date
    total_attempts: int
    total_correct_answers: int
    total_questions: int
    total_spend_time: int
    avg_correct_percentage: float
    overall_avg_time_per_question: float
    median_time_per_question: float
    avg_score: float = 0.0
    avg_spend_time: float = 0.0


class TopicStatisticServiceDTO(BaseModel):
    """Полная статистика тренажеров"""

    overall: TopicStatisticOverallDTO
    daily: list[TopicStatisticDailyDTO]
    streak: int = 0
    attempts: list[TopicAttemptDetailDTO]


class TrainerStatisticSummaryDTO(BaseModel):
    """Сводная статистика по тренажерам"""

    period_attempts_count: int
    period_total_questions: int = Field(default=0, description="Вопросов за период")
    period_correct_answers: int = Field(
        default=0, description="Правильных ответов за период"
    )
    period_accuracy: float = Field(default=0.0, description="Точность за период")

    overall_total_questions: int = Field(
        default=0, description="Всего вопросов за всё время"
    )
    overall_correct_answers: int = Field(
        default=0, description="Всего правильных ответов за всё время"
    )
    overall_accuracy: float = Field(
        default=0.0, description="Общая точность за всё время"
    )

    period_progress_by_topic: list[TopicProgressDTO] = Field(
        default_factory=list, description="Прогресс по темам за период"
    )
    period_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Прогресс по предметам за период"
    )
    overall_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Общий прогресс по предметам за всё время"
    )
    overall_progress_by_topic: list[TopicProgressDTO] = Field(
        default_factory=list, description="Общий прогресс по темам за всё время"
    )
    current_streak: int = Field(default=0, ge=0)
    total_spend_time_seconds: int = Field(
        default=0, description="Общее время, затраченное на Trainer тесты (в секундах)"
    )
    total_spend_time_formatted: str = Field(
        default="0s", description="Форматированное время Trainer тестов"
    )


# ==================== DAILY DTOs ====================


class DailyStatisticSummaryDTO(BaseModel):
    """Сводная статистика по ежедневным заданиям"""

    period_attempts_count: int
    period_total_questions: int = Field(default=0, description="Вопросов за период")
    period_correct_answers: int = Field(
        default=0, description="Правильных ответов за период"
    )
    period_accuracy: float = Field(default=0.0, description="Точность за период")

    overall_total_questions: int = Field(
        default=0, description="Всего вопросов за всё время"
    )
    overall_correct_answers: int = Field(
        default=0, description="Всего правильных ответов за всё время"
    )
    overall_accuracy: float = Field(
        default=0.0, description="Общая точность за всё время"
    )

    period_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Прогресс по предметам за период"
    )
    overall_progress_by_subject: list[SubjectProgressDTO] = Field(
        default_factory=list, description="Общий прогресс по предметам за всё время"
    )
    current_streak: int = Field(default=0, description="Текущая серия дней")
    total_spend_time_seconds: int = Field(
        default=0, description="Общее время, затраченное на Daily тесты (в секундах)"
    )
    total_spend_time_formatted: str = Field(
        default="0s", description="Форматированное время Daily тестов"
    )


# ==================== GLOBAL DTOs ====================


class PeriodInfoDTO(BaseModel):
    """Информация о периоде"""

    period_type: StatisticPeriodType
    start_date: date
    end_date: date
    description: str


class GlobalStatisticDTO(BaseModel):
    """Общая статистика по всем категориям"""

    period: str
    start_date: date
    end_date: date

    ent: EntStatisticDTO
    trainer: TrainerStatisticSummaryDTO
    daily: DailyStatisticSummaryDTO

    total_attempts: int
    total_questions: int
    total_correct_answers: int
    overall_accuracy: float

    @property
    def overall_accuracy_percentage(self) -> float:
        total_correct = self.total_correct_answers
        total_questions = self.total_questions
        return round(
            (total_correct / total_questions * 100) if total_questions > 0 else 0, 2
        )


class StreakHistoryItemDTO(BaseModel):
    date: date
    streak: bool


class EntStatisticSplitDTO(BaseModel):
    """Разделенная статистика ENT"""

    by_subject: EntStatisticSummaryDTO
    full_exam: EntStatisticSummaryDTO


class EnhancedGlobalStatisticDTO(BaseModel):
    """Расширенная глобальная статистика с разделением ENT"""

    period: str
    start_date: date
    end_date: date

    ent_statistics: EntStatisticSplitDTO
    trainer: TrainerStatisticSummaryDTO
    daily: DailyStatisticSummaryDTO

    total_attempts: int
    total_questions: int
    total_correct_answers: int
    overall_accuracy: float

    period_info: PeriodInfoDTO
    streak_history: list[StreakHistoryItemDTO]
    current_streak: int
    ent_subject_max_streak: int = Field(default=0, ge=0)
    ent_full_max_streak: int = Field(default=0, ge=0)
    trainer_max_streak: int = Field(default=0, ge=0)
    daily_max_streak: int = Field(default=0, ge=0)
    max_streak_in_period: int
    screen_time_history: list[ScreenTimeDailyDTO] = Field(
        default_factory=list, description="История экранного времени по дням"
    )
    screen_time_by_activity: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Экранное время по типам активности (ent_subject, ent_full, trainer, daily, other)",
    )
    total_screen_time_seconds: int = Field(
        default=0, description="Общее экранное время за период в секундах"
    )
    average_daily_screen_time_seconds: int = Field(
        default=0, description="Среднее экранное время в день в секундах"
    )
    average_daily_screen_time: str = Field(
        default="0m", description="Среднее экранное время в день (форматированное)"
    )
    activity_level: str
    engagement_score: float
    recommendations: list[str]

    @field_validator("screen_time_by_activity", mode="before")
    @classmethod
    def validate_screen_time_by_activity(cls, v):
        """Валидация screen_time_by_activity"""
        if not isinstance(v, dict):
            return v
        result = v.copy()
        for activity in ["ent_subject", "ent_full", "trainer", "daily", "other"]:
            if activity not in result:
                result[activity] = {
                    "total_seconds": 0,
                    "average_daily_seconds": 0,
                    "history": [],
                }
        return result


# ==================== REPOSITORY DTOs (для обратной совместимости) ====================


class EntStatisticRepositoryDTO(BaseModel):
    """Репозиторная DTO для общей статистики ЕНТ"""

    avg_score: float = 0.0
    tries: int = 0
    avg_spend_time: float = 0.0
    correct_answers: int = 0
    total_questions: int = 0
    skipped_answers: int = 0


class EntStatisticDailyRepositoryDTO(BaseModel):
    """Репозиторная DTO для ежедневной статистики ЕНТ"""

    date: date
    avg_score: float = 0.0
    tries: int = 0
    avg_spend_time: float = 0.0
    correct_answers: int = 0
    total_questions: int = 0
    skipped_answers: int = 0


class TopicStatisticRepositoryDTO(BaseModel):
    """Репозиторная DTO для общей статистики тренажеров"""

    total: int = 0
    correct: int = 0
    partial_correct: int = 0
    incorrect: int = 0
    skiped: int = 0
    avg_spend_time: float = 0.0


class TopicStatisticDailyRepositoryDTO(BaseModel):
    """Репозиторная DTO для ежедневной статистики тренажеров"""

    date: date
    total: int = 0
    correct: int = 0
    partial_correct: int = 0
    incorrect: int = 0
    skiped: int = 0
    avg_spend_time: float = 0.0


class EntStatisticGetRepositoryDTO(BaseModel):
    """Репозиторная DTO для запроса статистики ЕНТ"""

    student_guid: UUID
    ts_start: int
    ts_end: int


class TrainerAttemptStatisticDetailDTO(BaseModel):
    """Детальная статистика одной попытки тренера"""

    attempt_id: int
    score: int
    correct: int
    partial_correct: int = 0
    incorrect: int
    skiped: int
    total_questions: int
    spend_time: int

    @property
    def correct_percentage(self) -> float:
        if self.total_questions > 0:
            return (self.correct / self.total_questions) * 100
        return 0.0

    @property
    def avg_time_per_question(self) -> float:
        answered = self.total_questions - self.skiped
        if answered > 0:
            return self.spend_time / answered
        return 0.0


class TimeMetricsDTO(BaseModel):
    """Метрики времени"""

    total_session_seconds: int
    corrected_session_seconds: int
    active_seconds: int | None = None
    efficiency_ratio: float | None = None
    is_time_corrected: bool = False
    correction_reason: str | None = None


class EnhancedEntStatisticOverallDTO(EntStatisticOverallDTO):
    """Расширенная статистика ЕНТ с метриками времени"""

    time_metrics: TimeMetricsDTO

    @computed_field
    @property
    def realistic_avg_time_per_question(self) -> float:
        if self.total_questions > 0:
            return self.time_metrics.corrected_session_seconds / self.total_questions
        return 0.0


class EnhancedTopicStatisticOverallDTO(TopicStatisticOverallDTO):
    """Расширенная статистика тренажеров с метриками времени"""

    time_metrics: TimeMetricsDTO


class EnhancedEntAttemptDetailDTO(EntAttemptDetailDTO):
    """Детальная информация по попытке ЕНТ с метриками времени"""

    time_correction_applied: bool = False
    original_spend_time: int | None = None


class EnhancedTopicAttemptDetailDTO(TopicAttemptDetailDTO):
    """Детальная информация по попытке тренажера с метриками времени"""

    time_correction_applied: bool = False
    active_time_seconds: int | None = None


class EnhancedEntStatisticServiceDTO(EntStatisticServiceDTO):
    """Улучшенная статистика ЕНТ"""

    overall: EnhancedEntStatisticOverallDTO
    attempts: list[EnhancedEntAttemptDetailDTO]


class EnhancedTopicStatisticServiceDTO(TopicStatisticServiceDTO):
    """Улучшенная статистика тренажеров"""

    overall: EnhancedTopicStatisticOverallDTO
    attempts: list[EnhancedTopicAttemptDetailDTO]
