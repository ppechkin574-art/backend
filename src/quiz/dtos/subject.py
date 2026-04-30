from pydantic import BaseModel, ConfigDict

from quiz.dtos.enums import SubjectType
from quiz.dtos.topic import TopicRepositoryDTO


class SubjectCreateRepositoryDTO(BaseModel):
    name: str
    type: SubjectType
    image: str


class SubjectUpdateRepositoryDTO(BaseModel):
    name: str | None = None
    type: SubjectType | None = None
    image: str | None = None


class SubjectRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: SubjectType
    image: str
    topics: list[TopicRepositoryDTO]


class SubjectCreateServiceDTO(BaseModel):
    name: str
    type: SubjectType | None = SubjectType.specialized
    image: str | None = ""


class SubjectUpdateServiceDTO(BaseModel):
    name: str | None = None
    type: SubjectType | None = None
    image: str | None = None


class SubjectServiceDTO(BaseModel):
    id: int
    name: str
    type: SubjectType | None
    image: str | None


class SubjectServiceResponceDTO(BaseModel):
    count: int
    data: list[SubjectServiceDTO]


class SubjectWithStatsDTO(SubjectServiceDTO):
    topic_count: int = 0
    question_count: int = 0


class AdminSubjectStatsDTO(BaseModel):
    subject_id: int
    subject_name: str
    subject_image: str
    total_questions: int
    total_attempts: int
    average_success_rate: float
    average_time_per_question: float
