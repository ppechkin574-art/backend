from uuid import UUID

from pydantic import BaseModel, Field

from quiz.dtos.questions import QuestionServiceDTO


class TrainerCreateDTO(BaseModel):
    name: str
    topic_id: int


class TrainerUpdateDTO(BaseModel):
    name: str | None = None
    topic_id: int | None = None


class TrainerRepositoryDTO(BaseModel):
    id: int
    guid: UUID
    name: str
    topic_id: int


class TrainerServiceDTO(BaseModel):
    id: int
    guid: UUID
    name: str
    topic_id: int


class TrainerCreateServiceDTO(BaseModel):
    name: str
    topic_id: int


class TrainerWithQuestionsDTO(BaseModel):
    id: int
    name: str
    topic_id: int
    questions: list[QuestionServiceDTO] = Field(default_factory=list)


class TrainerWithStatsDTO(TrainerServiceDTO):
    question_count: int = 0


class TrainerUpdateServiceDTO(BaseModel):
    name: str | None = None
    topic_id: int | None = None


class TrainerUpdateRepositoryDTO(BaseModel):
    topic_id: int | None = None
    name: str | None = None
