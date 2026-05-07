"""Public content endpoints — read-only views over CMS-style data
(currently just `/content/subscription-benefits`).

These endpoints are intentionally unauthenticated: the data is shown
on the subscription screen which any user can reach (FREE included),
and we don't want to gate it behind a token round-trip."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_subscription_benefit_service
from content.dtos import Locale, SubscriptionBenefitPublicDTO
from content.service import SubscriptionBenefitService

router = APIRouter(prefix="/content", tags=["content"])


@router.get(
    "/subscription-benefits",
    response_model=list[SubscriptionBenefitPublicDTO],
    summary="Список фич подписки в выбранной локали",
    description=(
        "Активные пункты, отсортированные по `position`. "
        "Возвращаются с уже разрешённой локалью (`title`, `description`); "
        "по умолчанию RU. Для KZ передавать `?lang=kz`."
    ),
)
def get_subscription_benefits(
    lang: Annotated[Locale, Query(description="Локаль текстов: ru | kz")] = "ru",
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    return service.list_active_localised(lang)
