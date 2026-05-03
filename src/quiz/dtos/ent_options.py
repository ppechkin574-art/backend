from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quiz.dtos.ent_attempts import (
    EntAttemptOptionStatisticRepositoryDTO,
    EntAttemptOptionStatisticServiceDTO,
)
from quiz.dtos.questions import QuestionServiceDTO


class EntOptionsGetServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    student_guid: UUID
    subject_id: int | None = None


class EntOptionsGetRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    student_guid: UUID
    subject_id: int | None = None


class EntOptionsRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    option_number: int
    subject_id: int
    subject: str | None = None
    best_attempt: EntAttemptOptionStatisticRepositoryDTO | None = None


class EntOptionsServiceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    option_number: int
    subject_id: int
    subject: str | None = None
    best_attempt: EntAttemptOptionStatisticServiceDTO | None = None


class EntOptionsServiceResponceDTO(BaseModel):
    count: int
    data: list[EntOptionsServiceDTO]


class EntOptionCreateDTO(BaseModel):
    option_number: int
    subject_id: int


class EntOptionWithQuestionsDTO(BaseModel):
    id: int
    option_number: int
    subject_id: int
    questions: list[QuestionServiceDTO] = []


class EntOptionCreateServiceDTO(BaseModel):
    option_number: int
    subject_id: int


class EntOptionUpdateServiceDTO(BaseModel):
    option_number: int | None = None
    subject_id: int | None = None


class EntOptionUpdateDTO(BaseModel):
    option_number: int | None = None
    subject_id: int | None = None


class EntQuestionOperationDTO(BaseModel):
    question_ids: list[int]


class EntQuestionCheckDTO(BaseModel):
    question_id: int
    exists: bool


class EntQuestionsCountDTO(BaseModel):
    question_count: int
