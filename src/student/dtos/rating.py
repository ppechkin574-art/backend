from pydantic import BaseModel


class RatingQuestionDTO(BaseModel):
    weight: float


class RatingAnswerDTO(BaseModel):
    is_correct: bool
