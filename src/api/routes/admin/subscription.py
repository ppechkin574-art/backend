import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_db_session, allow_only_admins
from subscription.models import SubscriptionPlan
from subscription.plan_repository import SubscriptionPlanRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/subscription",
    tags=["Admin - Subscription"],
    dependencies=[Depends(allow_only_admins)],
)


class BenefitItemSchema(BaseModel):
    title: str
    description: str


class SubscriptionPlanAdminResponse(BaseModel):
    id: int
    plan_type: str
    name: str
    description: str | None
    price: float
    duration_days: int
    is_active: bool
    is_visible: bool
    display_order: int
    features: dict[str, Any] | None
    benefit_items: list[BenefitItemSchema] = Field(default_factory=list)


class UpdateSubscriptionPlanRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    is_active: bool | None = None
    is_visible: bool | None = None
    display_order: int | None = None
    benefit_items: list[BenefitItemSchema] | None = None


def _extract_benefit_items(features: dict | None) -> list[dict]:
    if not features:
        return []
    return features.get("benefit_items") or []


@router.get("/plans", response_model=list[SubscriptionPlanAdminResponse])
def list_plans(db: Session = Depends(get_db_session)):
    repo = SubscriptionPlanRepository(db)
    plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.display_order).all()
    result = []
    for plan in plans:
        features = plan.features or {}
        result.append(
            SubscriptionPlanAdminResponse(
                id=plan.id,
                plan_type=plan.plan_type,
                name=plan.name,
                description=plan.description,
                price=float(plan.price),
                duration_days=plan.duration_days,
                is_active=plan.is_active,
                is_visible=plan.is_visible,
                display_order=plan.display_order,
                features={k: v for k, v in features.items() if k != "benefit_items"},
                benefit_items=[BenefitItemSchema(**i) for i in _extract_benefit_items(features)],
            )
        )
    return result


@router.put("/plans/{plan_id}", response_model=SubscriptionPlanAdminResponse)
def update_plan(
    plan_id: int,
    data: UpdateSubscriptionPlanRequest,
    db: Session = Depends(get_db_session),
):
    repo = SubscriptionPlanRepository(db)
    plan = repo.get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if data.name is not None:
        plan.name = data.name
    if data.description is not None:
        plan.description = data.description
    if data.price is not None:
        if data.price <= 0:
            raise HTTPException(status_code=400, detail="Price must be positive")
        plan.price = data.price
    if data.is_active is not None:
        plan.is_active = data.is_active
    if data.is_visible is not None:
        plan.is_visible = data.is_visible
    if data.display_order is not None:
        plan.display_order = data.display_order

    if data.benefit_items is not None:
        features = dict(plan.features or {})
        features["benefit_items"] = [i.model_dump() for i in data.benefit_items]
        plan.features = features

    db.commit()
    db.refresh(plan)

    features = plan.features or {}
    return SubscriptionPlanAdminResponse(
        id=plan.id,
        plan_type=plan.plan_type,
        name=plan.name,
        description=plan.description,
        price=float(plan.price),
        duration_days=plan.duration_days,
        is_active=plan.is_active,
        is_visible=plan.is_visible,
        display_order=plan.display_order,
        features={k: v for k, v in features.items() if k != "benefit_items"},
        benefit_items=[BenefitItemSchema(**i) for i in _extract_benefit_items(features)],
    )
