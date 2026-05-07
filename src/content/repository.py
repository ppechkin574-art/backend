from sqlalchemy.orm import Session

from content.models import SubscriptionBenefit


class SubscriptionBenefitRepository:
    """Thin DB wrapper for the `subscription_benefits` table.

    Kept intentionally close to `SubscriptionPlanRepository` style so a
    new dev reading either of them can apply the same mental model.
    """

    def __init__(self, session: Session):
        self.session = session

    def list_active(self) -> list[SubscriptionBenefit]:
        """Active rows, ordered by `position` then `id` for stable sort
        when several rows share the same position number."""
        return (
            self.session.query(SubscriptionBenefit)
            .filter(SubscriptionBenefit.is_active.is_(True))
            .order_by(SubscriptionBenefit.position.asc(), SubscriptionBenefit.id.asc())
            .all()
        )

    def list_all(self) -> list[SubscriptionBenefit]:
        """Everything for the admin UI (including inactive entries)."""
        return (
            self.session.query(SubscriptionBenefit)
            .order_by(SubscriptionBenefit.position.asc(), SubscriptionBenefit.id.asc())
            .all()
        )

    def get(self, benefit_id: int) -> SubscriptionBenefit | None:
        return self.session.query(SubscriptionBenefit).filter(SubscriptionBenefit.id == benefit_id).first()

    def create(self, **fields) -> SubscriptionBenefit:
        benefit = SubscriptionBenefit(**fields)
        self.session.add(benefit)
        self.session.commit()
        self.session.refresh(benefit)
        return benefit

    def update(self, benefit_id: int, **fields) -> SubscriptionBenefit | None:
        benefit = self.get(benefit_id)
        if benefit is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(benefit, key, value)
        self.session.commit()
        self.session.refresh(benefit)
        return benefit

    def delete(self, benefit_id: int) -> bool:
        benefit = self.get(benefit_id)
        if benefit is None:
            return False
        self.session.delete(benefit)
        self.session.commit()
        return True
