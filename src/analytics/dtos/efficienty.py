from pydantic import BaseModel

from analytics.dtos.enums import MistakeCategory


class PopularEntityDTO(BaseModel):
    name: str
    attempts: int


class HardTopicDTO(BaseModel):
    name: str
    mistake_percent: int
    mistake_category: MistakeCategory


class EntEfficientyDTO(BaseModel):
    total_attempts: int
    avg_score: float
    avg_time: float
    popular_subjects: list[PopularEntityDTO]


class TrainerEfficientyDTO(BaseModel):
    total_attempts: int
    avg_score: float
    avg_anwer_time: float
    popular_topics: list[PopularEntityDTO] | None
    hard_topics: list[HardTopicDTO] | None


class ProgressEfficientyDTO(BaseModel):
    total_topics: int
    completed_topics: int
    avg_progress_percent: float


class EfficientyDTO(BaseModel):
    ent: EntEfficientyDTO
    trainer: TrainerEfficientyDTO
    progress: ProgressEfficientyDTO
