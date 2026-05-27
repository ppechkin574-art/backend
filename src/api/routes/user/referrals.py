"""User-facing referral-code endpoints.

Three things the client does:
  - GET  /user/referral/my-code   — show me my personal code (mint on first call)
  - POST /user/referral/redeem    — apply someone else's code to me
  - GET  /user/referral/invitees  — who used my code, did they pay

The policy values (stars + days for each side) are returned alongside
the code so the UI can render «получишь +N звёзд» without a second
roundtrip. Admin tunes those via /admin/app-settings.
"""

from fastapi import APIRouter, Depends

from api.dependencies import get_referral_service, get_user
from auth.dtos.users import UserDTO
from referrals.dtos import (
    InviteeStatusDTO,
    MyReferralCodeDTO,
    RedeemRequestDTO,
    RedemptionResultDTO,
    ReferralPolicyDTO,
)
from referrals.service import ReferralService

router = APIRouter(
    prefix="/user/referral",
    tags=["User - Referrals"],
    dependencies=[Depends(get_user)],
)


@router.get("/my-code", response_model=MyReferralCodeDTO)
def get_my_code(
    user: UserDTO = Depends(get_user),
    service: ReferralService = Depends(get_referral_service),
):
    """Возвращает (создавая при первом обращении) личный реферальный
    код. Идемпотентно — повторные вызовы возвращают тот же код."""
    return service.get_or_create_my_code(user.id)


@router.get("/policy", response_model=ReferralPolicyDTO)
def get_policy(
    service: ReferralService = Depends(get_referral_service),
):
    """Текущие награды по реферальной программе (редактируются через
    /admin/app-settings). UI использует чтобы показать пользователю
    что он получит ещё до ввода кода."""
    return service.get_policy()


@router.post("/redeem", response_model=RedemptionResultDTO)
def redeem(
    body: RedeemRequestDTO,
    user: UserDTO = Depends(get_user),
    service: ReferralService = Depends(get_referral_service),
):
    """Принимает чужой реферальный код. Возможен только 1 раз за всю
    историю аккаунта (DB-уровневая уникальность по invitee_id).
    Бизнес-правила (свой код, формат, повтор) бросают 4xx с понятным
    русским detail, который клиент показывает как текст ошибки."""
    return service.redeem(invitee_id=user.id, code=body.code)


@router.get("/invitees", response_model=list[InviteeStatusDTO])
def list_invitees(
    user: UserDTO = Depends(get_user),
    service: ReferralService = Depends(get_referral_service),
):
    """История приглашённых — для блока «Кого я пригласил» в профиле."""
    return service.list_invitees(user.id)
