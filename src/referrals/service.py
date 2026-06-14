"""Referral-code service: own code, redeem someone else's, list invitees.

Reward grant flow (operator decision 27.05.2026 — instant on redeem,
no conversion gating):
1. Validate code + invitee eligibility (one redemption per account, ever).
2. Persist a `ReferralRedemption` row WITH the policy snapshot — the
   actual stars/days granted, not the live policy values, so a later
   admin tweak doesn't rewrite history.
3. Commit the redemption + in-DB star grants as ONE transaction. The
   unique constraint on invitee_id is the atomic guard against a
   concurrent double-redeem — the loser's commit fails → 409 and its
   star writes roll back with it.
4. Grant Pro days (Keycloak — OUTSIDE the DB transaction) only AFTER
   the commit succeeds, so the race-loser never grants and a failed
   commit can't leave Pro days dangling without a redemption row. A
   grant failure is logged for a reconciliation job (not built yet).

Anti-farm: the inviter earns a reward for at most
`referral_inviter_max_rewards` invitees (default 25). Past that the
invitee still gets their bonus but the inviter earns nothing more —
neutralises the "spin up N throwaway accounts to farm my own code"
abuse.

Policy values live in `app_settings`:
  - referral_inviter_stars        (default 100)
  - referral_inviter_days         (default 7)
  - referral_invitee_stars        (default 30)
  - referral_invitee_days         (default 7)
  - referral_inviter_max_rewards  (default 25)
"""

import hashlib
import logging
import random
import re
import string
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app_config.service import AppSettingsService
from auth.admin_service import AdminUserService
from payments.models import Payment
from quiz.repositories.user_points import UserPointsRepository
from referrals.dtos import (
    InviteeStatusDTO,
    MyReferralCodeDTO,
    ReferralPolicyDTO,
    RedemptionResultDTO,
)
from referrals.models import ReferralCode, ReferralRedemption
from utils.file_service import FileService

logger = logging.getLogger(__name__)

# Letters minus visually ambiguous ones (O, I, L) — easier for users to
# read a code off a screenshot or hand-write it without errors.
_CODE_LETTERS = "".join(c for c in string.ascii_uppercase if c not in "OIL")
_CODE_DIGITS = string.digits

_POLICY_KEYS = {
    "inviter_stars": ("referral_inviter_stars", 100),
    "inviter_days": ("referral_inviter_days", 7),
    "invitee_stars": ("referral_invitee_stars", 30),
    "invitee_days": ("referral_invitee_days", 7),
}

# Anti-farm cap: max invitees an inviter earns a reward for. Tunable
# from the admin panel; 0 disables the inviter reward entirely. The
# invitee always gets their own bonus regardless of this cap.
_INVITER_CAP_KEY = ("referral_inviter_max_rewards", 99999)

_CODE_FORMAT_RE = re.compile(r"^[A-Z]{3}\d{3}[A-Z]{2}$")


class ReferralService:
    def __init__(
        self,
        db: Session,
        app_settings: AppSettingsService,
        admin_user_service: AdminUserService,
        user_points_repo: UserPointsRepository,
        file_service: FileService,
    ):
        self.db = db
        self.app_settings = app_settings
        self.admin_user_service = admin_user_service
        self.user_points_repo = user_points_repo
        self.file_service = file_service

    # ─── public reads ─────────────────────────────────────────────────

    def get_or_create_my_code(self, user_id: UUID) -> MyReferralCodeDTO:
        """Idempotent — first call mints the user's lifetime code,
        every subsequent call returns the same row."""
        row = self.db.query(ReferralCode).filter(ReferralCode.user_id == user_id).first()
        if row is None:
            row = self._mint_unique_code(user_id)
        return MyReferralCodeDTO(code=row.code, created_at=row.created_at)

    def get_policy(self) -> ReferralPolicyDTO:
        return ReferralPolicyDTO(
            inviter_stars=self.app_settings.get_int(*_POLICY_KEYS["inviter_stars"]),
            inviter_days=self.app_settings.get_int(*_POLICY_KEYS["inviter_days"]),
            invitee_stars=self.app_settings.get_int(*_POLICY_KEYS["invitee_stars"]),
            invitee_days=self.app_settings.get_int(*_POLICY_KEYS["invitee_days"]),
        )

    def list_invitees(self, inviter_id: UUID) -> list[InviteeStatusDTO]:
        rows = (
            self.db.query(ReferralRedemption)
            .filter(ReferralRedemption.inviter_id == inviter_id)
            .order_by(ReferralRedemption.redeemed_at.desc())
            .all()
        )
        out: list[InviteeStatusDTO] = []
        for r in rows:
            avatar_url: str | None = None
            try:
                user = self.admin_user_service.get_user(r.invitee_id)
                display = user.name or self._mask_phone(user.phone)
                # Avatar is a flattened Keycloak attribute (bare filename) on
                # UserDTO. Presign it for the client. Fail-soft: any hiccup
                # leaves avatar_url None and the client falls back to the
                # letter-initial — never break the row over a missing photo.
                if user.avatar:
                    try:
                        avatar_url = self.file_service.get_avatar_url(user.avatar) or None
                    except Exception as e:
                        logger.warning(
                            "Failed to presign avatar for invitee %s: %s",
                            r.invitee_id,
                            e,
                        )
                        avatar_url = None
            except Exception as e:
                # Don't fail the whole list just because Keycloak hiccupped
                # on one invitee — show a placeholder and move on.
                logger.warning("Failed to fetch invitee %s: %s", r.invitee_id, e)
                display = "—"
            out.append(
                InviteeStatusDTO(
                    invitee_id=r.invitee_id,
                    invitee_display_name=display,
                    invitee_avatar_url=avatar_url,
                    redeemed_at=r.redeemed_at,
                )
            )
        return out

    # ─── public writes ────────────────────────────────────────────────

    def redeem(self, invitee_id: UUID, code: str) -> RedemptionResultDTO:
        """Apply a code on behalf of `invitee_id`. On every business-rule
        fail raises HTTPException with a Russian `detail` (printed verbatim
        by the old app) AND an `X-Error-Code` header (the new app localizes
        off it)."""
        code = code.strip().upper()

        if not _CODE_FORMAT_RE.match(code):
            raise self._redeem_error(
                status.HTTP_400_BAD_REQUEST, "bad_format", "Неверный формат промокода"
            )

        owner = self.db.query(ReferralCode).filter(ReferralCode.code == code).first()
        if owner is None:
            raise self._redeem_error(
                status.HTTP_404_NOT_FOUND, "unknown", "Такой промокод не существует"
            )
        if owner.user_id == invitee_id:
            raise self._redeem_error(
                status.HTTP_400_BAD_REQUEST,
                "self_code",
                "Нельзя вводить свой собственный код",
            )

        # Resolve invitee phone hash — survives account deletion + re-registration.
        # Fail-soft: if Keycloak is temporarily unavailable we still allow the
        # redeem but without the phone-level guard (UUID-level guard still applies).
        invitee_phone_hash: str | None = None
        try:
            invitee_user = self.admin_user_service.get_user(invitee_id)
            if invitee_user.phone:
                invitee_phone_hash = hashlib.sha256(
                    invitee_user.phone.encode()
                ).hexdigest()
        except Exception:
            logger.warning(
                "Could not resolve phone hash for invitee %s — UUID-only check applies",
                invitee_id,
            )

        # Fast, friendly pre-check for the common "already used" case.
        # Checks BOTH uuid AND phone hash so the same number can't redeem
        # twice after deleting and re-registering (different UUID, same phone).
        # The DB unique constraints are the REAL guard against concurrent races.
        already_redeemed_filter = [ReferralRedemption.invitee_id == invitee_id]
        if invitee_phone_hash:
            already_redeemed_filter = [
                or_(
                    ReferralRedemption.invitee_id == invitee_id,
                    ReferralRedemption.invitee_phone_hash == invitee_phone_hash,
                )
            ]
        already_redeemed = (
            self.db.query(ReferralRedemption)
            .filter(*already_redeemed_filter)
            .first()
        )
        if already_redeemed is not None:
            raise self._redeem_error(
                status.HTTP_409_CONFLICT,
                "already_redeemed",
                "Ты уже использовал промокод. Один код на аккаунт.",
            )

        policy = self.get_policy()

        # Anti-farm cap. Count only previously-REWARDED redemptions so the
        # count is stable once the cap is hit (capped ones store 0 and
        # don't inflate it). Past the cap the invitee still gets THEIR
        # bonus; the inviter earns nothing.
        cap = self.app_settings.get_int(*_INVITER_CAP_KEY)
        rewarded_invitees = (
            self.db.query(ReferralRedemption)
            .filter(
                ReferralRedemption.inviter_id == owner.user_id,
                ReferralRedemption.inviter_stars_granted > 0,
            )
            .count()
        )
        reward_inviter = rewarded_invitees < cap

        # Inviter reward: only if inviter has at least one real paid subscription
        # (trial does not count). If inviter has never paid — they get 0.
        inviter_has_paid = reward_inviter and self._has_ever_paid(owner.user_id)
        inviter_stars = policy.inviter_stars if inviter_has_paid else 0
        inviter_days = policy.inviter_days if inviter_has_paid else 0

        # Persist the redemption. Invitee fields are a SNAPSHOT (promise) —
        # actual grant happens on the invitee's first real payment.
        # invitee_rewarded_at=None marks the reward as pending.
        redemption = ReferralRedemption(
            code_id=owner.user_id,
            inviter_id=owner.user_id,
            invitee_id=invitee_id,
            invitee_phone_hash=invitee_phone_hash,
            inviter_stars_granted=inviter_stars,
            inviter_days_granted=inviter_days,
            invitee_stars_granted=policy.invitee_stars,
            invitee_days_granted=policy.invitee_days,
            invitee_rewarded_at=None,
        )
        self.db.add(redemption)
        self.db.flush()
        redemption_id = redemption.id

        # Inviter stars are in-DB → part of THIS transaction.
        if inviter_has_paid and inviter_stars > 0:
            self.user_points_repo.add_points(owner.user_id, inviter_stars)

        # Invitee stars: DEFERRED — granted by grant_pending_invitee_reward()
        # when the invitee makes their first real payment.

        # Commit FIRST. The unique constraint on invitee_id is the atomic
        # guard against a concurrent second redemption: the loser's commit
        # raises IntegrityError, we surface the same friendly 409, its star
        # writes roll back, and it never reaches the Pro-day grant below.
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise self._redeem_error(
                status.HTTP_409_CONFLICT,
                "already_redeemed",
                "Ты уже использовал промокод. Один код на аккаунт.",
            )

        # Pro days for inviter: touch Keycloak OUTSIDE the DB transaction.
        if inviter_has_paid:
            self._grant_pro_days_safe(
                owner.user_id, inviter_days, redemption_id, "inviter"
            )
        # Pro days for invitee: DEFERRED — see grant_pending_invitee_reward().

        return RedemptionResultDTO(
            inviter_id=owner.user_id,
            invitee_stars_granted=policy.invitee_stars,
            invitee_days_granted=policy.invitee_days,
            inviter_stars_granted=inviter_stars,
            inviter_days_granted=inviter_days,
            invitee_reward_pending=True,
        )

    # ─── internals ────────────────────────────────────────────────────

    @staticmethod
    def _redeem_error(status_code: int, code: str, detail: str) -> HTTPException:
        """Business-rule rejection. `detail` stays a plain Russian string
        so the OLD app (which prints `detail` verbatim) keeps working; the
        machine-readable `X-Error-Code` header lets the NEW app localize."""
        return HTTPException(
            status_code=status_code,
            detail=detail,
            headers={"X-Error-Code": code},
        )

    def _grant_pro_days_safe(
        self, user_id: UUID, days: int, redemption_id: int, side: str
    ) -> None:
        """Best-effort Pro-day grant (Keycloak). Never raises — a failure
        is loud-logged and left for the reconciliation job; the committed
        redemption row is the source of truth for what was owed."""
        if days <= 0:
            return
        try:
            self.admin_user_service.grant_pro_subscription(user_id=user_id, days=days)
        except Exception as e:
            logger.exception(
                "Failed to grant %s Pro days (redemption %s): %s",
                side,
                redemption_id,
                e,
            )

    def _mint_unique_code(self, user_id: UUID) -> ReferralCode:
        """Try up to 8 random codes — collision is astronomically
        unlikely (29^5 × 10^3 = ~17M combos vs at most thousands of
        users), but a retry is cheap insurance against birthday-paradox
        bad luck."""
        for _ in range(8):
            candidate = self._generate_code()
            existing = (
                self.db.query(ReferralCode.code)
                .filter(ReferralCode.code == candidate)
                .first()
            )
            if existing is None:
                row = ReferralCode(user_id=user_id, code=candidate)
                self.db.add(row)
                self.db.commit()
                self.db.refresh(row)
                logger.info("Minted referral code %s for user %s", candidate, user_id)
                return row
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сгенерировать уникальный код. Попробуйте позже.",
        )

    @staticmethod
    def _generate_code() -> str:
        # Format: 3 letters + 3 digits + 2 letters (e.g. EJW123JX)
        letters3 = "".join(random.choices(_CODE_LETTERS, k=3))
        digits3 = "".join(random.choices(_CODE_DIGITS, k=3))
        letters2 = "".join(random.choices(_CODE_LETTERS, k=2))
        return letters3 + digits3 + letters2

    def _has_ever_paid(self, user_id: UUID) -> bool:
        """True if the user has at least one successful paid subscription.
        Trial (1-day free) does NOT count — only real money payments.
        Checks the payments table which is populated by all 3 payment flows
        (FreedomPay, Apple IAP, Google Play).
        """
        return (
            self.db.query(Payment)
            .filter(
                Payment.user_id == str(user_id),
                Payment.status == "paid",
            )
            .first()
        ) is not None

    @staticmethod
    def _mask_phone(phone: str | None) -> str:
        # Fallback when user hasn't set a username — show last 4 digits.
        if not phone:
            return "—"
        digits = "".join(c for c in phone if c.isdigit())
        return f"+…{digits[-4:]}" if len(digits) >= 4 else "—"


def grant_pending_invitee_reward(
    user_id: UUID,
    db: Session,
    user_points_repo: UserPointsRepository,
    admin_user_service: AdminUserService,
) -> bool:
    """Grant a deferred referral reward to the invitee after their first real payment.

    Called from every payment confirmation handler (FreedomPay webhook, Apple IAP,
    Android IAP). Idempotent: does nothing if the reward was already granted or
    if the user has no pending referral redemption.

    Returns True if a reward was granted, False if nothing to do.
    """
    row = (
        db.query(ReferralRedemption)
        .filter(
            ReferralRedemption.invitee_id == user_id,
            ReferralRedemption.invitee_rewarded_at.is_(None),
        )
        .first()
    )
    if row is None:
        return False

    if row.invitee_stars_granted > 0:
        user_points_repo.add_points(user_id, row.invitee_stars_granted)

    if row.invitee_days_granted > 0:
        try:
            admin_user_service.grant_pro_subscription(
                user_id=user_id, days=row.invitee_days_granted
            )
        except Exception:
            logger.exception(
                "Failed to grant referral Pro days to invitee %s", user_id
            )

    row.invitee_rewarded_at = datetime.now(UTC)
    db.flush()

    logger.info(
        "Referral reward granted to invitee %s: stars=%s days=%s",
        user_id,
        row.invitee_stars_granted,
        row.invitee_days_granted,
    )
    return True
