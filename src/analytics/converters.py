from pydantic import BaseModel

from analytics.dtos.enums import UserActivityEnum
from analytics.dtos.events import EventCreateRepositoryDTO, EventCreateServiceDTO
from analytics.dtos.metas import (
    AppCrashedMetaDTO,
    EntCompleteMetaDTO,
    EntStartMetaDTO,
    PurchaseFailedMetaDTO,
    PurchaseInitMetaDTO,
    PurchaseSuccessMetaDTO,
    TrainerAnswerMetaDTO,
    TrainerCompletedMetaDTO,
    TrainerStartMetaDTO,
    UserLoggedInMetaDTO,
    UserRegisteredMetaDTO,
)
from analytics.dtos.payments import (
    LastPaymentRepositoryDTO,
    LastPaymentServiceDTO,
    TopClientRepositoryDTO,
    TopClientServiceDTO,
)
from auth.dtos.users import UserDTO


def to_event_create_repository(event_dto: EventCreateServiceDTO):
    def is_valid_meta(meta: dict, dto_class: BaseModel):
        try:
            dto_class.model_validate(meta)
            return True
        except Exception:
            return False

    valid_meta = True
    if event_dto.meta:
        match event_dto.event_name:
            case UserActivityEnum.app_crashed.value:
                valid_meta = is_valid_meta(event_dto.meta, AppCrashedMetaDTO)
            case UserActivityEnum.user_registered.value:
                valid_meta = is_valid_meta(event_dto.meta, UserRegisteredMetaDTO)
            case UserActivityEnum.user_logged_in.value:
                valid_meta = is_valid_meta(event_dto.meta, UserLoggedInMetaDTO)
            case UserActivityEnum.ent_subject_started.value:
                valid_meta = is_valid_meta(event_dto.meta, EntStartMetaDTO)
            case UserActivityEnum.ent_subject_completed.value:
                valid_meta = is_valid_meta(event_dto.meta, EntCompleteMetaDTO)
            case UserActivityEnum.trainer_started.value:
                valid_meta = is_valid_meta(event_dto.meta, TrainerStartMetaDTO)
            case UserActivityEnum.trainer_answer.value:
                valid_meta = is_valid_meta(event_dto.meta, TrainerAnswerMetaDTO)
            case UserActivityEnum.trainer_completed.value:
                valid_meta = is_valid_meta(event_dto.meta, TrainerCompletedMetaDTO)
            case UserActivityEnum.purchase_initiated.value:
                valid_meta = is_valid_meta(event_dto.meta, PurchaseInitMetaDTO)
            case UserActivityEnum.purchase_success.value:
                valid_meta = is_valid_meta(event_dto.meta, PurchaseSuccessMetaDTO)
            case UserActivityEnum.purchase_failed.value:
                valid_meta = is_valid_meta(event_dto.meta, PurchaseFailedMetaDTO)
            case _:
                pass
    return EventCreateRepositoryDTO.model_validate(event_dto), valid_meta


def to_last_payment_service(repo_dto: LastPaymentRepositoryDTO, user: UserDTO) -> LastPaymentServiceDTO:
    return LastPaymentServiceDTO(
        payment_id=repo_dto.payment_id,
        user_id=repo_dto.user_id,
        amount=repo_dto.amount,
        status=repo_dto.status,
        method=repo_dto.method,
        date=repo_dto.date,
        month=repo_dto.month,
        user_fio=user.name,
        email=user.email,
    )


def to_top_client_service(repo_dto: TopClientRepositoryDTO, user: UserDTO) -> TopClientServiceDTO:
    return TopClientServiceDTO(
        user_id=repo_dto.user_id,
        total_amount=repo_dto.total_amount,
        total_payments=repo_dto.total_payments,
        last_payment_date=repo_dto.last_payment_date,
        user_fio=user.name,
        email=user.email,
    )
