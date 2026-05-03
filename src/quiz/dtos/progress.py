# backend/src/quiz/dtos/progress.py
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def format_progress(value: float) -> float:
    """Форматировать прогресс с двумя знаками после запятой"""
    if value is None:
        return 0.0
    return round(float(value), 2)


class TopicProgressDTO(BaseModel):
    """Прогресс по теме - просто число от 0 до 1"""

    id: int
    name: str
    subject_id: int
    progress: float


class SubjectProgressDTO(BaseModel):
    """Прогресс по предмету - просто число от 0 до 1"""

    id: int
    name: str
    type: str
    image: str | None = None
    progress: float


class TrainerProgressDetailDTO(BaseModel):
    """Детали прогресса по тренажёру"""

    trainer_id: int
    trainer_name: str
    topic_id: int
    topic_name: str
    progress: float = Field(ge=0.0, le=1.0)
    best_score: int | None = None
    attempt_count: int = 0
    total_questions: int = 0
    correct_questions: int = 0

    @field_validator("progress", mode="before")
    @classmethod
    def format_progress(cls, v):
        return round(float(v), 2) if v is not None else 0.0


class EntOptionProgressDetailDTO(BaseModel):
    """Детали прогресса по варианту ЕНТ"""

    option_id: int
    option_number: int
    subject_id: int
    subject_name: str
    progress: float = Field(ge=0.0, le=1.0)
    best_score: int | None = None
    attempt_count: int = 0
    total_questions: int = 0
    correct_questions: int = 0
    last_attempt_at: datetime | None = None

    @field_validator("progress", mode="before")
    @classmethod
    def format_progress(cls, v):
        return round(float(v), 2) if v is not None else 0.0


class TrainersProgressSummaryDTO(BaseModel):
    """Сводка прогресса по всем тренажёрам"""

    total_trainers: int
    completed_trainers: int
    overall_progress: float = Field(ge=0.0, le=1.0)

    @field_validator("overall_progress", mode="before")
    @classmethod
    def format_progress(cls, v):
        return format_progress(v)

    @classmethod
    def from_values(cls, total: int, completed: int, progress: float):
        """Альтернативный конструктор"""
        return cls(
            total_trainers=total,
            completed_trainers=completed,
            overall_progress=format_progress(progress),
        )


class EntOptionsProgressSummaryDTO(BaseModel):
    """Сводка прогресса по всем вариантам ЕНТ"""

    total_options: int
    completed_options: int
    overall_progress: float = Field(ge=0.0, le=1.0)

    @field_validator("overall_progress", mode="before")
    @classmethod
    def format_progress(cls, v):
        return format_progress(v)

    @classmethod
    def from_values(cls, total: int, completed: int, progress: float):
        """Альтернативный конструктор"""
        return cls(
            total_options=total,
            completed_options=completed,
            overall_progress=format_progress(progress),
        )


class UserProgressOverviewDTO(BaseModel):
    """Общий обзор прогресса пользователя"""

    subjects_progress: float
    topics_progress: float
    trainers_progress: float
    ent_options_progress: float
    overall_progress: float
    total_attempts: int
    streak_days: int

    @field_validator(
        "subjects_progress",
        "topics_progress",
        "trainers_progress",
        "ent_options_progress",
        "overall_progress",
        mode="before",
    )
    def format_progress(cls, v):
        return format_progress(v)
