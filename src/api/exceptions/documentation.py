from typing import Any

from fastapi import status

from api.exceptions.errors import (
    AuthErrorResponse,
    ConflictErrorResponse,
    ForbiddenErrorResponse,
    ImportErrorResponse,
    InternalErrorResponse,
    NotFoundErrorResponse,
    QuizErrorResponse,
    SimpleErrorResponse,
    SubscriptionErrorResponse,
    UnauthorizedErrorResponse,
    ValidationErrorResponse,
)
from auth.exceptions import (
    AuthAccessInvalidTokenError,
    AuthBadCredentialsError,
    AuthConfirmationCodeExpiredError,
    AuthFailedConfirmationError,
    AuthInvalidConfirmationCodeError,
    AuthInvalidRefreshTokenError,
    AuthNotVerifiedError,
    AuthUnauthorizedError,
    AuthUserEmailExistsError,
    AuthUserExistsError,
    AuthUserNotFoundError,
    AuthUserPhoneExistsError,
    ConfirmationCodeExistsError,
    ConfirmationCodeNotFoundError,
    TemporaryRegistrationNotFoundError,
    UserBadCredentialsError,
    UserEmailExistsError,
    UserExistsError,
    UserInvalidAccessTokenError,
    UserInvalidRefreshTokenError,
    UserNotFoundError,
    UserNotVerifiedError,
    UserPhoneExistsError,
)
from promocodes.exceptions import (
    PromocodeActivationError,
    PromocodeAlreadyUsedError,
    PromocodeExpiredError,
    PromocodeInvalidError,
    PromocodeNotFoundError,
)
from quiz.exceptions import (
    AlreadyAnswered,
    AttemptCompleted,
    AttemptNotCompleted,
    DeadlineExceeded,
    EntOptionAlreadyExist,
    EntOptionsDoesntExist,
    HintNotFound,
    ImageNotSavedError,
    InvalidFormat,
    InvalidImportData,
    MissingColumns,
    NoQuestionsInTrainerAttempt,
    QuestionNotFound,
    StatisticDoesNotExist,
    SubjectAlreadyExists,
    SubjectIdViolatesNotNullService,
    SubjectIntegrityErrorService,
    SubjectNotFound,
    SubjectNotFoundService,
    TestQuestionNotExist,
    TestTypeDontImport,
    TopicAlreadyExists,
    TopicIdViolatesNotNullService,
    TopicNotFound,
    TopicNotFoundService,
    TopicsMergeError,
    TopicSubjectNotFoundService,
    TrainerAttemptNotExist,
    TrainerNotFound,
    VariantNotExist,
    WrongStudent,
)
from subscription.exceptions import InsufficientPlanError, SubscriptionRequired

EXCEPTION_DOCS: dict[type[Exception], dict] = {
    # Auth Exceptions
    AuthBadCredentialsError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid credentials",
        "model": AuthErrorResponse,
    },
    AuthUserExistsError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "User already exists",
        "model": AuthErrorResponse,
    },
    AuthUserNotFoundError: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "User not found",
        "model": AuthErrorResponse,
    },
    AuthInvalidConfirmationCodeError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Invalid confirmation code",
        "model": AuthErrorResponse,
    },
    AuthConfirmationCodeExpiredError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Confirmation code expired",
        "model": AuthErrorResponse,
    },
    AuthFailedConfirmationError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Confirmation code sending error",
        "model": AuthErrorResponse,
    },
    AuthAccessInvalidTokenError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid access token",
        "model": AuthErrorResponse,
    },
    AuthInvalidRefreshTokenError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid refresh token",
        "model": AuthErrorResponse,
    },
    AuthNotVerifiedError: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "User not verified",
        "model": AuthErrorResponse,
    },
    # User exceptions
    UserNotFoundError: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "User not found",
        "model": AuthErrorResponse,
    },
    UserEmailExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Email already in use",
        "model": AuthErrorResponse,
    },
    UserPhoneExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Phone already in use",
        "model": AuthErrorResponse,
    },
    UserExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "User already exists",
        "model": AuthErrorResponse,
    },
    UserBadCredentialsError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid credentials",
        "model": AuthErrorResponse,
    },
    UserInvalidAccessTokenError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid access token",
        "model": AuthErrorResponse,
    },
    UserInvalidRefreshTokenError: {
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "description": "Invalid refresh token",
        "model": AuthErrorResponse,
    },
    UserNotVerifiedError: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "User not verified",
        "model": AuthErrorResponse,
    },
    # ConfirmationCode exceptions
    ConfirmationCodeExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Confirmation code already exists",
        "model": AuthErrorResponse,
    },
    ConfirmationCodeNotFoundError: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Confirmation code not found",
        "model": AuthErrorResponse,
    },
    TemporaryRegistrationNotFoundError: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Temporary registration not found",
        "model": AuthErrorResponse,
    },
    # 400 - Bad Request
    AlreadyAnswered: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Question already answered",
        "model": QuizErrorResponse,
    },
    AttemptCompleted: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Attempt already completed",
        "model": QuizErrorResponse,
    },
    AttemptNotCompleted: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Attempt is not completed",
        "model": QuizErrorResponse,
    },
    VariantNotExist: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Specified answer variant does not exist",
        "model": QuizErrorResponse,
    },
    InvalidFormat: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Invalid data format",
        "model": ImportErrorResponse,
    },
    InvalidImportData: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Invalid data for import",
        "model": ImportErrorResponse,
    },
    TestTypeDontImport: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "This test type does not support import",
        "model": ImportErrorResponse,
    },
    TopicsMergeError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Topics merge validation error",
        "model": QuizErrorResponse,
    },
    MissingColumns: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Missing required columns in the file",
        "model": ImportErrorResponse,
    },
    # 403 - Forbidden
    WrongStudent: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "Access denied - wrong user",
        "model": ForbiddenErrorResponse,
    },
    AuthUnauthorizedError: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "Access denied",
        "model": ForbiddenErrorResponse,
    },
    # 404 - Not Found
    QuestionNotFound: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Question not found",
        "model": NotFoundErrorResponse,
    },
    HintNotFound: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Hint not found",
        "model": NotFoundErrorResponse,
    },
    TopicNotFound: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Topic not found",
        "model": NotFoundErrorResponse,
    },
    SubjectNotFound: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Subject not found",
        "model": NotFoundErrorResponse,
    },
    TrainerAttemptNotExist: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Trainer attempt not found",
        "model": NotFoundErrorResponse,
    },
    TrainerNotFound: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Trainer not found",
        "model": NotFoundErrorResponse,
    },
    NoQuestionsInTrainerAttempt: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "No questions in the trainer attempt",
        "model": NotFoundErrorResponse,
    },
    TestQuestionNotExist: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Test question not found",
        "model": NotFoundErrorResponse,
    },
    EntOptionsDoesntExist: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "ENT option not found",
        "model": NotFoundErrorResponse,
    },
    StatisticDoesNotExist: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Statistic not found",
        "model": NotFoundErrorResponse,
    },
    SubjectNotFoundService: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Subject not found (service)",
        "model": NotFoundErrorResponse,
    },
    TopicNotFoundService: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Topic not found (service)",
        "model": NotFoundErrorResponse,
    },
    TopicSubjectNotFoundService: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Topic subject not found",
        "model": NotFoundErrorResponse,
    },
    # 409 - Conflict
    SubjectIntegrityErrorService: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Subject data integrity conflict",
        "model": ConflictErrorResponse,
    },
    SubjectAlreadyExists: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Subject with this name already exists",
        "model": ConflictErrorResponse,
    },
    TopicAlreadyExists: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Topic with this name already exists",
        "model": ConflictErrorResponse,
    },
    EntOptionAlreadyExist: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "ENT option already exists",
        "model": ConflictErrorResponse,
    },
    AuthUserEmailExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Email already in use",
        "model": AuthErrorResponse,
    },
    AuthUserPhoneExistsError: {
        "status_code": status.HTTP_409_CONFLICT,
        "description": "Phone already in use",
        "model": AuthErrorResponse,
    },
    # 422 - Unprocessable Entity
    SubjectIdViolatesNotNullService: {
        "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "description": "Cannot delete subject - data integrity violation",
        "model": SimpleErrorResponse,
    },
    TopicIdViolatesNotNullService: {
        "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "description": "Cannot delete topic - data integrity violation",
        "model": SimpleErrorResponse,
    },
    ImageNotSavedError: {
        "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "description": "Image saving error",
        "model": SimpleErrorResponse,
    },
    DeadlineExceeded: {
        "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "description": "Execution time has expired",
        "model": SimpleErrorResponse,
    },
    # Promocode Exceptions
    PromocodeActivationError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Promocode activation failed",
        "model": SimpleErrorResponse,
    },
    PromocodeNotFoundError: {
        "status_code": status.HTTP_404_NOT_FOUND,
        "description": "Promocode not found",
        "model": SimpleErrorResponse,
    },
    PromocodeExpiredError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Promocode expired",
        "model": SimpleErrorResponse,
    },
    PromocodeAlreadyUsedError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Promocode already used",
        "model": SimpleErrorResponse,
    },
    PromocodeInvalidError: {
        "status_code": status.HTTP_400_BAD_REQUEST,
        "description": "Invalid promocode",
        "model": SimpleErrorResponse,
    },
    SubscriptionRequired: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "Active subscription required",
        "model": SubscriptionErrorResponse,
    },
    InsufficientPlanError: {
        "status_code": status.HTTP_403_FORBIDDEN,
        "description": "Higher subscription plan required",
        "model": SubscriptionErrorResponse,
    },
}


def get_error_responses(*exceptions: type[Exception]) -> dict[int, dict[str, Any]]:
    """
    Generates responses dictionary for FastAPI based on provided exceptions
    """
    responses: dict[int, dict[str, Any]] = {}
    for exc in exceptions:
        if exc in EXCEPTION_DOCS:
            doc = EXCEPTION_DOCS[exc]
            responses[doc["status_code"]] = {
                "model": doc["model"],
                "description": doc["description"],
            }
    return responses


def get_common_responses(operation_type: str = "read") -> dict[int, dict[str, Any]]:
    """
    Returns common responses for different types of operations
    """
    common: dict[int, dict[str, Any]] = {
        status.HTTP_401_UNAUTHORIZED: {
            "model": UnauthorizedErrorResponse,
            "description": "Unauthorized",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ForbiddenErrorResponse,
            "description": "Access denied",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ValidationErrorResponse,
            "description": "Data validation error",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": InternalErrorResponse,
            "description": "Internal server error",
        },
    }

    if operation_type == "create":
        common[status.HTTP_400_BAD_REQUEST] = {
            "model": SimpleErrorResponse,
            "description": "Invalid data",
        }
    elif operation_type == "update":
        common[status.HTTP_400_BAD_REQUEST] = {
            "model": SimpleErrorResponse,
            "description": "Invalid data for update",
        }

    return common


def get_daily_test_responses(operation_type: str = "read") -> dict[int, dict[str, Any]]:
    """
    Returns common responses for daily test endpoints
    Includes TrainerAttemptNotExist and AlreadyAnswered errors
    """
    responses = get_common_responses(operation_type)
    responses.update(get_error_responses(TrainerAttemptNotExist, AlreadyAnswered))
    return responses


def get_ent_responses(operation_type: str = "read") -> dict[int, dict[str, Any]]:
    """
    Returns common responses for ENT test endpoints
    Includes common ENT errors
    """
    responses = get_common_responses(operation_type)
    responses.update(
        get_error_responses(
            TrainerAttemptNotExist,
            AlreadyAnswered,
            WrongStudent,
            EntOptionsDoesntExist,
            VariantNotExist,
            QuestionNotFound,
        )
    )
    return responses
