"""Admin CRUD endpoints for subscription benefits.

Gated by `allow_read_or_admin_write` — only realm-role `admin` can mutate the
list.  Behavioural contract:

- GET   /admin/content/subscription-benefits           — list everything (incl. inactive)
- GET   /admin/content/subscription-benefits/{id}      — one row
- POST  /admin/content/subscription-benefits           — create
- PATCH /admin/content/subscription-benefits/{id}      — partial update
- DELETE /admin/content/subscription-benefits/{id}     — hard delete

The admin UI lives in the `aima-admin` repo and consumes these endpoints
through its existing OpenAPI client."""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import allow_read_or_admin_write, get_subscription_benefit_service
from content.dtos import (
    SubscriptionBenefitAdminDTO,
    SubscriptionBenefitCreateDTO,
    SubscriptionBenefitUpdateDTO,
)
from content.service import SubscriptionBenefitService

router = APIRouter(
    prefix="/admin/content/subscription-benefits",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get(
    "",
    response_model=list[SubscriptionBenefitAdminDTO],
    summary="Все фичи (вкл. неактивные)",
)
def list_benefits(
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    return service.list_all_admin()


@router.get(
    "/{benefit_id}",
    response_model=SubscriptionBenefitAdminDTO,
    summary="Получить одну фичу",
)
def get_benefit(
    benefit_id: int,
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    benefit = service.get_admin(benefit_id)
    if benefit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benefit not found")
    return benefit


@router.post(
    "",
    response_model=SubscriptionBenefitAdminDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Создать фичу",
)
def create_benefit(
    body: SubscriptionBenefitCreateDTO,
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    return service.create(body)


@router.patch(
    "/{benefit_id}",
    response_model=SubscriptionBenefitAdminDTO,
    summary="Обновить фичу (партиально)",
)
def update_benefit(
    benefit_id: int,
    body: SubscriptionBenefitUpdateDTO,
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    benefit = service.update(benefit_id, body)
    if benefit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benefit not found")
    return benefit


@router.delete(
    "/{benefit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить фичу",
)
def delete_benefit(
    benefit_id: int,
    service: SubscriptionBenefitService = Depends(get_subscription_benefit_service),
):
    if not service.delete(benefit_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benefit not found")
