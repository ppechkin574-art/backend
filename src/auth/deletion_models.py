"""Soft-delete queue for user accounts.

When a user requests account deletion, a row is created here with
`scheduled_for = now + 30 days`. The Keycloak account is NOT immediately
deleted — it remains active so the user can cancel during the grace period.

A background task (lifespan.py) polls this table every hour and hard-deletes
Keycloak accounts whose `scheduled_for` has elapsed and `executed_at` is NULL.

The 30-day window:
- Prevents instant delete → re-register loops that bypass per-account limits.
- Gives payment processors time to process chargebacks before the account vanishes.
- Lets the user cancel if they changed their mind.
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database import Base

DELETION_GRACE_DAYS = 30


class AccountDeletionRequest(Base):
    __tablename__ = "account_deletion_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Keycloak UUID of the user requesting deletion.
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    # sha256(phone) — stored so we can block referral re-abuse even after hard-delete.
    phone_hash = Column(String(64), nullable=True, index=True)
    requested_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Hard-delete executes at or after this timestamp.
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    # Set when the background task actually removes the Keycloak account.
    # NULL means pending; NOT NULL means executed.
    executed_at = Column(DateTime(timezone=True), nullable=True)
