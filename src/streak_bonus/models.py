"""Daily-streak coin bonus — tracks both the operator-editable
reward tiers and the per-user-per-day claim history.

Reward is awarded on top of the existing `attendance_streak` system:
the streak count itself is computed by the attendance pipeline, this
module ONLY hands out coins (credited to the user's Bank balance)
once per day when the user has an active streak day.

Two tables:
- `streak_reward_tiers`  operator-editable thresholds (min_streak → coins).
                         Service picks the highest tier whose
                         `min_streak <= current_streak` AND is_active.
- `streak_bonus_claims`  one row per user per local-KZ day. UNIQUE
                         (user_id, claim_date) prevents double-claim
                         if the client retries.
"""

from sqlalchemy import (
    UUID,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from database import Base


class StreakRewardTier(Base):
    __tablename__ = "streak_reward_tiers"

    # `min_streak` is the PK because each threshold is unique: there
    # is at most one tier for «day 1+», one for «day 7+», etc. Admin
    # editing «change the day-7 reward from 200 → 250 coins» is a
    # straight UPDATE on that PK row.
    min_streak = Column(Integer, primary_key=True)
    coins = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StreakBonusClaim(Base):
    """One claim per user per local-KZ day.

    `claim_date` is stored as a `Date` (no time) so the UNIQUE on
    (user_id, claim_date) reliably blocks double-claims regardless
    of when in the day the user opened the app. Service computes
    the date using `to_kz_date(datetime.utcnow())` to keep the
    «day boundary» consistent with how the attendance system
    defines a calendar day for KZ users.
    """

    __tablename__ = "streak_bonus_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    claim_date = Column(Date, nullable=False)
    # Snapshot of the streak count at the moment of the claim — admin
    # editing tier thresholds later doesn't rewrite past claims.
    streak_at_claim = Column(Integer, nullable=False)
    coins_credited = Column(Integer, nullable=False)
    claimed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "claim_date", name="uq_streak_bonus_claims_user_date"
        ),
    )


class StreakPushTemplate(Base):
    """Singleton settings row for the «streak about to expire» push.

    Cron fires daily at `(00:00 - hours_before_reset)` Asia/Almaty and
    sends a reminder to every student whose streak ≥ 1 and who hasn't
    claimed today's bonus yet. Title/body support a `{streak}` placeholder
    that the service substitutes per user; the row is editable from the
    admin panel so operators can tweak copy without a redeploy.
    """

    __tablename__ = "streak_push_template"

    # Hardcoded id=1 + CHECK forces a single row — easier UX in admin
    # (one form, no list / no «which row?» ambiguity).
    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, server_default="true")
    title = Column(String(200), nullable=False)
    body = Column(String(500), nullable=False)
    hours_before_reset = Column(Integer, nullable=False, server_default="8")
    timezone = Column(String(64), nullable=False, server_default="Asia/Almaty")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_streak_push_template_singleton"),
        CheckConstraint(
            "hours_before_reset BETWEEN 1 AND 23",
            name="ck_streak_push_template_hours",
        ),
    )
