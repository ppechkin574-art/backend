from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EntOptionQuestionCreateDTO(BaseModel):
    ent_option_id: int
    question_id: int


class EntOptionQuestionRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    ent_option_id: int
    question_id: int


class EntOptionQuestionServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guid: UUID
    ent_option_id: int
    question_id: int


class EntQuestionsUpdateDTO(BaseModel):
    subject_id: int | None = None
