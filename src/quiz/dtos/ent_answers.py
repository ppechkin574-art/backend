from uuid import UUID

from pydantic import BaseModel


class EntQuestionServiceDTO(BaseModel):
    question_id: int
    variants: list[int]
    spend_time: int | None = None


class EntAttemptAnswerServiceDTO(BaseModel):
    student_guid: UUID
    ent_attempt_id: int
    questions: list[EntQuestionServiceDTO]
    total_session_spend_time: int | None = None


class EntAttemptAnswerCreateRepositoryDTO(BaseModel):
    ent_attempt_id: int
    variant_id: int | None = None
