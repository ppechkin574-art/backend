"""User-to-user referral codes (distinct from admin-issued Promocode).

Each registered user has exactly one personal `ReferralCode`. Anyone
can redeem someone else's code at most once in their entire account
lifetime (operator policy 27.05.2026). When redeemed, both inviter
and invitee get a configurable bundle of leaderboard stars + Pro days
— the policy values live in `app_settings` so they can be tuned from
the admin panel without a redeploy.

Why a separate table from `Promocode`:
- Promocode is admin-issued, one-shot or N-shot, single-sided reward.
- ReferralCode is user-owned, unlimited activations, two-sided reward.
- Different lifecycle, anti-abuse, and admin UI — keeping the two
  schemas apart makes both simpler.
"""

from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from database import Base


class ReferralCode(Base):
    """One row per user — their personal invitation code.

    Created lazily on first GET /user/referral/my-code (no need to
    backfill for existing users until they open the screen).
    """

    __tablename__ = "referral_codes"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    code = Column(String(16), unique=True, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ReferralRedemption(Base):
    """Records one invitee redeeming one inviter's code.

    Unique constraint on `invitee_id` enforces the operator's rule:
    one promo per user per account lifetime (no second redemption
    even after a year). Self-redemption is blocked at the service
    layer (the FK alone can't express "inviter != invitee").

    `invitee_phone_hash` (sha256 of phone) is stored alongside invitee_id
    so the same phone number cannot redeem a code even after deleting and
    re-registering (which produces a new UUID but the same phone).
    """

    __tablename__ = "referral_redemptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_id = Column(
        ForeignKey("referral_codes.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inviter_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    invitee_id = Column(UUID(as_uuid=True), nullable=False)
    # sha256(phone) — survives account deletion + re-registration.
    # Nullable only for rows created before this column was added.
    invitee_phone_hash = Column(String(64), nullable=True)
    redeemed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Snapshot of the policy values applied AT redemption time so a
    # later admin tweak to `app_settings` doesn't retroactively rewrite
    # what each user was promised.
    inviter_stars_granted = Column(Integer, nullable=False)
    inviter_days_granted = Column(Integer, nullable=False)
    # For invitee: these are the PROMISED amounts (snapshot at redemption).
    # Actual grant happens on first paid subscription — see invitee_rewarded_at.
    invitee_stars_granted = Column(Integer, nullable=False)
    invitee_days_granted = Column(Integer, nullable=False)
    # NULL = reward pending (invitee has not paid yet).
    # NOT NULL = reward already granted at this timestamp.
    # Rows created before this column existed have invitee_rewarded_at = redeemed_at
    # (set by migration) — they were granted immediately under the old policy.
    invitee_rewarded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One promo per invitee lifetime — DB-enforced.
        UniqueConstraint("invitee_id", name="uq_referral_redemptions_invitee"),
        # Same phone number cannot redeem across account churn (partial — excludes NULLs).
        Index(
            "uix_referral_redemptions_phone_hash",
            "invitee_phone_hash",
            unique=True,
            postgresql_where=text("invitee_phone_hash IS NOT NULL"),
        ),
    )
