"""Wire shapes for the referral feature.

Public API surface:
- GET  /user/referral/my-code      → MyReferralCodeDTO
- POST /user/referral/redeem       → RedemptionResultDTO
- GET  /user/referral/invitees     → list[InviteeStatusDTO]
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MyReferralCodeDTO(BaseModel):
    code: str = Field(..., description="Личный реферальный код юзера, формат XXX###XX")
    created_at: datetime


class RedeemRequestDTO(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)


class RedemptionResultDTO(BaseModel):
    """Returned to the invitee after a successful redemption — also
    surfaced in the inviter's notification."""

    inviter_id: UUID
    invitee_stars_granted: int
    invitee_days_granted: int
    inviter_stars_granted: int
    inviter_days_granted: int
    invitee_reward_pending: bool = Field(
        default=True,
        description=(
            "True если награда инвайти отложена до первой оплаты. "
            "Фронт должен показать: «Звёзды будут начислены после первой покупки подписки»."
        ),
    )


class InviteeStatusDTO(BaseModel):
    """One row in «Кого я пригласил» list on the profile screen."""

    invitee_id: UUID
    invitee_display_name: str  # display name or masked phone fallback
    invitee_avatar_url: str | None = Field(
        default=None,
        description=(
            "Presigned URL аватара приглашённого. None/«» если у юзера нет "
            "аватара или presign не удался — клиент показывает букву-инициал."
        ),
    )
    redeemed_at: datetime


class ReferralPolicyDTO(BaseModel):
    """Effective reward bundle. Read from app_settings, used in API
    response so the client can render «получишь +N звёзд и +M дней»
    BEFORE the user submits the code."""

    inviter_stars: int
    inviter_days: int
    invitee_stars: int
    invitee_days: int
