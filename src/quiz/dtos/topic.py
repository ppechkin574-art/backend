from pydantic import BaseModel, ConfigDict


class TopicCreateRepositoryDTO(BaseModel):
    subject_id: int
    name: str


class TopicUpdateRepositoryDTO(BaseModel):
    subject_id: int
    name: str | None = None


class TopicRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    name: str


class TopicCreateServiceDTO(BaseModel):
    subject_id: int
    name: str


class TopicUpdateServiceDTO(BaseModel):
    subject_id: int
    name: str


class TopicServiceDTO(BaseModel):
    id: int
    subject_id: int
    name: str


class TopicServiceResponceDTO(BaseModel):
    count: int
    data: list[TopicServiceDTO]


class TopicWithStatsDTO(TopicServiceDTO):
    question_count: int = 0
