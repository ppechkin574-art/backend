from pydantic import BaseModel, ConfigDict


class TrainerAttemptQuestionRepositoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    trainer_attempt_id: int
    question_id: int
    spend_time: int = 0
