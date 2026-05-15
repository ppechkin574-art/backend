import logging

from fastapi import APIRouter, Depends

from api.dependencies import get_subscription_benefit_service
from content.dtos import SubscriptionBenefitPublicDTO
from content.service import SubscriptionBenefitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["Content"])


@router.get(
    "/subscription-benefits",
    response_model=list[SubscriptionBenefitPublicDTO],
    summary="Преимущества подписки PRO",
)
async def get_subscription_benefits(
    lang: str = "ru",
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
) -> list[SubscriptionBenefitPublicDTO]:
    """Live list of subscription bullets, sourced from the `subscription_benefits`
    table and filtered to `is_active=True`. Admins manage rows via
    `/admin/content/subscription-benefits/...` — the mobile app sees changes
    immediately on next fetch (modulo the client-side cache).

    Previously this endpoint returned a hardcoded list — that became a silent
    no-op once the admin panel went live, because deactivated rows still
    showed up on the subscription screen. Replaced with the service so the
    admin UI is the single source of truth.
    """
    locale = "kz" if lang.lower() in ("kz", "kk") else "ru"
    return service.list_active_localised(locale)
