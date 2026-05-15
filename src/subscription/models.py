from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.enums import PlanType, SubscriptionStatus
from database import Base


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True)
    plan_type = Column(String(32), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    price = Column(Numeric(12, 2), nullable=False, default=0)
    original_price = Column(Numeric(12, 2), nullable=True)
    duration_days = Column(Integer, nullable=False, default=30)
    is_recurring = Column(Boolean, default=True)
    trial_days = Column(Integer, default=0)
    features = Column(JSON, nullable=True, default=list)
    limitations = Column(JSON, nullable=True, default=dict)

    is_active = Column(Boolean, default=True, index=True)
    is_visible = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    subscriptions = relationship("Subscription", back_populates="subscription_plan")

    __table_args__ = (
        UniqueConstraint("plan_type", name="uq_subscription_plan_type"),
        Index("ix_subscription_plans_active", "is_active", "is_visible"),
    )

    def __repr__(self):
        return f"SubscriptionPlan(id={self.id}, name={self.name}, price={self.price})"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)

    subscription_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)
    subscription_plan = relationship("SubscriptionPlan", back_populates="subscriptions")

    plan = Column(String(32), nullable=False, default=PlanType.FREE.value)

    status = Column(String(32), nullable=False, default=SubscriptionStatus.PENDING.value)
    started_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    auto_renew = Column(Boolean, default=True)

    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)

    promocode_usage_id = Column(Integer, ForeignKey("promocode_usages.id"), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    payment = relationship("Payment", back_populates="subscription", uselist=False)

    __table_args__ = (
        Index("ix_subscriptions_user_status", "user_id", "status"),
        Index("ix_subscriptions_expires_at", "expires_at"),
        Index("ix_subscriptions_plan", "subscription_plan_id"),
    )

    def is_active(self):
        """Проверяет, активна ли подписка"""
        if self.status != SubscriptionStatus.ACTIVE.value:
            return False
        if self.plan == PlanType.FREE.value:
            return True
        if self.plan == PlanType.PRO.value:
            if not self.expires_at:
                return False
            return self.expires_at > datetime.now(UTC)
        return False

    def __repr__(self):
        return f"Subscription(id={self.id}, user_id={self.user_id}, status={self.status})"


class SubscriptionHistory(Base):
    __tablename__ = "subscription_history"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    old_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=False)
    event_type = Column(String(64), nullable=False)
    history_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_subscription_history_subscription_id", "subscription_id"),
        Index("ix_subscription_history_created_at", "created_at"),
    )


class TrialHistory(Base):
    """Phone-level (not user-level) audit of free trials granted.

    The Keycloak user has a `used_trial` attribute that's the primary
    gate, but it disappears when the user record is deleted. This table
    keeps a sha256(phone) marker that survives user deletion so the
    same number can't redeem a free trial twice across account churn.

    Append-only: we never update or delete rows. If a number genuinely
    needs a second trial (rare ops case), the row can be removed via
    direct DB intervention.
    """

    __tablename__ = "trial_history"

    phone_hash = Column(String(64), primary_key=True)
    first_granted_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"TrialHistory(phone_hash={self.phone_hash[:8]}..., at={self.first_granted_at})"
