from pydantic import BaseModel


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    detail: list[ValidationErrorItem]


class SimpleErrorResponse(BaseModel):
    detail: str


class AuthErrorResponse(BaseModel):
    detail: str


class ConflictErrorResponse(BaseModel):
    detail: str
    existing_topic_id: int | None = None
    existing_subject_id: int | None = None


class NotFoundErrorResponse(BaseModel):
    detail: str


class ForbiddenErrorResponse(BaseModel):
    detail: str


class UnauthorizedErrorResponse(BaseModel):
    detail: str


class InternalErrorResponse(BaseModel):
    detail: str


# class AuthTokensDTO(BaseModel):
#     access_token: str
#     refresh_token: str


# class AuthConfirmationDTO(BaseModel):
#     confirmation_id: UUID


class QuizErrorResponse(BaseModel):
    detail: str


class ImportErrorResponse(BaseModel):
    detail: str
    errors: list[str] | None = None


# class PaymentErrorResponse(BaseModel):
#     detail: str
#     order_id: str | None = None


# class PromocodeErrorResponse(BaseModel):
#     detail: str


class SubscriptionErrorResponse(BaseModel):
    detail: str
    required_plan: str | None = None
    current_plan: str | None = None
