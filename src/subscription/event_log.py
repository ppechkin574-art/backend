"""Single audit trail for every subscription money/lifecycle event.

One append-only table across ALL platforms (Apple, Google, admin) so support
can answer "я заплатил, где PRO?" from one place: purchase, renewal, expiry,
refund, revoke, restore, verify-rejected, admin grant/reset. Never updated or
deleted.

`log_subscription_event` is best-effort and commits its OWN row — call it at a
point where the surrounding session is otherwise clean (right after the main
commit), so its commit can't accidentally flush half-finished work and a
failure here can never break the purchase response.
"""

from __future__ import annotations

import contextlib

import logging
from decimal import Decimal

from sqlalchemy import Column, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database import Base

logger = logging.getLogger(__name__)


class SubscriptionEventLog(Base):
    __tablename__ = "subscription_event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id = Column(String, nullable=True, index=True)
    platform = Column(String, nullable=False)  # apple / google / admin
    # purchase / renew / expire / refund / revoke / restore /
    # verify_rejected / grant_admin / reset_admin / activate_failed
    event_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)  # success / failed
    product_id = Column(String, nullable=True)
    transaction_id = Column(String, nullable=True, index=True)
    amount = Column(Numeric(12, 2), nullable=True)
    environment = Column(String, nullable=True)  # Sandbox / Production
    detail = Column(String, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SubscriptionEventLog {self.platform}/{self.event_type}"
            f" {self.status} user={self.user_id}>"
        )


def log_subscription_event(
    session: Session,
    *,
    platform: str,
    event_type: str,
    status: str,
    user_id: str | None = None,
    product_id: str | None = None,
    transaction_id: str | None = None,
    amount: Decimal | None = None,
    environment: str | None = None,
    detail: str | None = None,
) -> None:
    """Append one audit row. Never raises; never breaks the caller."""
    try:
        session.add(
            SubscriptionEventLog(
                platform=platform,
                event_type=event_type,
                status=status,
                user_id=str(user_id) if user_id else None,
                product_id=product_id,
                transaction_id=transaction_id,
                amount=amount,
                environment=environment,
                detail=detail,
            )
        )
        session.commit()
    except Exception:  # noqa: BLE001 — audit must never break the payment flow
        with contextlib.suppress(Exception):
            session.rollback()
        logger.exception(
            "[audit] failed to log subscription event %s/%s", platform, event_type
        )
