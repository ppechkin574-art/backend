import logging
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from common.enums import PlanType
from subscription.models import SubscriptionPlan
from subscription.plan_repository import SubscriptionPlanRepository

logger = logging.getLogger(__name__)


class SubscriptionPlanService:
    def __init__(self, plan_repository: SubscriptionPlanRepository):
        self.plan_repository = plan_repository

    def get_available_plans(self) -> list[SubscriptionPlan]:
        """Получить доступные планы для покупки"""
        return self.plan_repository.get_active_plans()

    def get_plan_by_id(self, plan_id: int) -> SubscriptionPlan:
        """Получить план по ID"""
        plan = self.plan_repository.get_plan_by_id(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan

    def get_plan_by_type(self, plan_type: PlanType) -> SubscriptionPlan:
        """Получить план по типу"""
        plan = self.plan_repository.get_plan_by_type(plan_type)
        if not plan:
            raise HTTPException(status_code=404, detail=f"Plan {plan_type} not found")
        return plan

    def create_plan(self, plan_data: dict[str, Any]) -> SubscriptionPlan:
        """Создать новый план"""
        existing_plan = self.plan_repository.get_plan_by_type(plan_data["plan_type"])
        if existing_plan:
            raise HTTPException(
                status_code=400,
                detail=f"Plan with type {plan_data['plan_type']} already exists",
            )

        if plan_data["price"] <= 0:
            raise HTTPException(status_code=400, detail="Price must be positive")

        if plan_data.get("original_price") and plan_data["original_price"] <= plan_data["price"]:
            raise HTTPException(
                status_code=400,
                detail="Original price must be greater than current price for discount",
            )

        return self.plan_repository.create_plan(plan_data)

    def update_plan(self, plan_id: int, plan_data: dict[str, Any]) -> SubscriptionPlan:
        """Обновить план"""
        plan = self.get_plan_by_id(plan_id)

        if "plan_type" in plan_data and plan_data["plan_type"] != plan.plan_type:
            existing_plan = self.plan_repository.get_plan_by_type(plan_data["plan_type"])
            if existing_plan and existing_plan.id != plan_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Plan with type {plan_data['plan_type']} already exists",
                )

        if "price" in plan_data and plan_data["price"] <= 0:
            raise HTTPException(status_code=400, detail="Price must be positive")

        updated_plan = self.plan_repository.update_plan(plan_id, plan_data)
        if not updated_plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        return updated_plan

    def calculate_price_for_months(self, plan: SubscriptionPlan, months: int) -> Decimal:
        """Рассчитать стоимость для указанного количества месяцев"""
        if plan.duration_days == 30:
            return plan.price * months
        else:
            price_per_day = plan.price / plan.duration_days
            return price_per_day * (months * 30)
