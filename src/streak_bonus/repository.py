from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from streak_bonus.models import (
    StreakBonusClaim,
    StreakPushTemplate,
    StreakRewardTier,
)


class StreakBonusRepository:
    def __init__(self, db: Session):
        self.db = db

    # ─── reward tiers (admin) ────────────────────────────────────────

    def list_tiers(self, *, only_active: bool = False) -> list[StreakRewardTier]:
        stmt = select(StreakRewardTier).order_by(StreakRewardTier.min_streak)
        if only_active:
            stmt = stmt.where(StreakRewardTier.is_active.is_(True))
        return list(self.db.scalars(stmt).all())

    def get_tier(self, min_streak: int) -> StreakRewardTier | None:
        return self.db.get(StreakRewardTier, min_streak)

    def create_tier(self, tier: StreakRewardTier) -> StreakRewardTier:
        self.db.add(tier)
        self.db.flush()
        return tier

    def delete_tier(self, tier: StreakRewardTier) -> None:
        self.db.delete(tier)
        self.db.flush()

    # ─── claims (user) ───────────────────────────────────────────────

    def get_claim_for_date(
        self, user_id: UUID, claim_date: date
    ) -> StreakBonusClaim | None:
        return self.db.scalars(
            select(StreakBonusClaim).where(
                StreakBonusClaim.user_id == user_id,
                StreakBonusClaim.claim_date == claim_date,
            )
        ).first()

    def create_claim(self, claim: StreakBonusClaim) -> StreakBonusClaim:
        self.db.add(claim)
        self.db.flush()
        return claim

    # ─── push template (admin singleton) ────────────────────────────

    def get_push_template(self) -> StreakPushTemplate | None:
        return self.db.get(StreakPushTemplate, 1)
