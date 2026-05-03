from pydantic import BaseModel, ConfigDict


class AppCrashedMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    error: str


class UserRegisteredMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: str  # email/phone


class UserLoggedInMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: str  # apple/google/common


class EntStartMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ent_option_id: int


class EntCompleteMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ent_option_id: int
    score: int
    spend_time: int


class TrainerStartMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trainer_id: int


class TrainerAnswerMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trainer_id: int
    question_id: int
    score: float
    spend_time: int


class TrainerCompletedMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trainer_id: int
    correct: int
    incorrect: int


class PurchaseInitMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: int
    method: str
    amount: float
    month: int
    promo: str | None


class PurchaseSuccessMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: int
    method: str
    amount: float
    month: int
    promo: str | None


class PurchaseFailedMetaDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: int
    method: str
    amount: float
    month: int
    error: str
