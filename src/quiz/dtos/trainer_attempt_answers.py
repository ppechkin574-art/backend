from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TrainerAttemptAnswerRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    trainer_attempt_question_id: int
    variant_id: int


class TrainerAttemptAnswerServiceDTO(BaseModel):
    id: int | None
    trainer_attempt_question_id: int
    variant_id: int


class TestAnswerServiceDTO(BaseModel):
    student_guid: UUID
    trainer_attempt_question_id: int
    variants: list[int]
    spend_time: int


class TrainerAttemptAnswerCreateRepositoryDTO(BaseModel):
    trainer_attempt_question_id: int
    variant_id: int
    student_guid: UUID
