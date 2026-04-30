from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from common.enums import PlanType
from subscription.models import SubscriptionPlan


class SubscriptionPlanRepository:
    def __init__(self, session: Session):
        self.session = session

    # def get_all_plans(self) -> list[SubscriptionPlan]:
    #     """Получить все планы"""
    #     return self.session.query(SubscriptionPlan).order_by(SubscriptionPlan.display_order).all()

    def get_active_plans(self) -> list[SubscriptionPlan]:
        """Получить активные и видимые планы"""
        return (
            self.session.query(SubscriptionPlan)
            .filter(
                and_(
                    SubscriptionPlan.is_active,
                    SubscriptionPlan.is_visible,
                )
            )
            .order_by(SubscriptionPlan.display_order)
            .all()
        )

    def get_plan_by_id(self, plan_id: int) -> SubscriptionPlan | None:
        """Получить план по ID"""
        return self.session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()

    def get_plan_by_type(self, plan_type: PlanType) -> SubscriptionPlan | None:
        """Получить план по типу"""
        return self.session.query(SubscriptionPlan).filter(SubscriptionPlan.plan_type == plan_type.value).first()

    def create_plan(self, plan_data: dict[str, Any]) -> SubscriptionPlan:
        """Создать новый план"""
        plan = SubscriptionPlan(**plan_data)
        self.session.add(plan)
        self.session.commit()
        self.session.refresh(plan)
        return plan

    def update_plan(self, plan_id: int, plan_data: dict[str, Any]) -> SubscriptionPlan | None:
        """Обновить план"""
        plan = self.get_plan_by_id(plan_id)
        if not plan:
            return None

        for key, value in plan_data.items():
            setattr(plan, key, value)

        self.session.commit()
        self.session.refresh(plan)
        return plan

    # def delete_plan(self, plan_id: int) -> bool:
    #     """Удалить план (мягкое удаление - деактивация)"""
    #     plan = self.get_plan_by_id(plan_id)
    #     if not plan:
    #         return False

    #     plan.is_active = False
    #     plan.is_visible = False
    #     self.session.commit()
    #     return True
