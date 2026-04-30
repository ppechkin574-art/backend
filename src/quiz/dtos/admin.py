from uuid import UUID

from pydantic import BaseModel

from .enums import SubjectType


class AdminSubjectDTO(BaseModel):
    id: int
    name: str
    type: SubjectType
    image: str | None = None
    topic_count: int
    question_count: int
    topics: list["AdminTopicDTO"] = []


class AdminTopicDTO(BaseModel):
    id: int
    name: str
    subject_id: int
    question_count: int
    trainer_count: int
    trainers: list["AdminTrainerDTO"] = []


class AdminTrainerDTO(BaseModel):
    id: int
    guid: UUID
    name: str
    topic_id: int
    question_count: int


class AdminEntOptionDTO(BaseModel):
    id: int
    option_number: int
    subject_id: int
    subject_name: str
    question_count: int
    # for feature may be added fields:
    # attempts_count: int = 0
    # average_score: float = 0.0


class AdminDashboardDTO(BaseModel):
    subjects: list[AdminSubjectDTO]
    topics: list[AdminTopicDTO]
    trainers: list[AdminTrainerDTO]
    ent_options: list[AdminEntOptionDTO]
    total_stats: dict[str, int]


AdminSubjectDTO.model_rebuild()
AdminTopicDTO.model_rebuild()
AdminTrainerDTO.model_rebuild()
