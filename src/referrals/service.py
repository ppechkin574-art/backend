"""Referral-code service: own code, redeem someone else's, list invitees.

Reward grant flow (operator decision 27.05.2026 — instant, no
conversion gating):
1. Validate code + invitee eligibility (one redemption per account, ever).
2. Persist a `ReferralRedemption` row WITH the policy snapshot — the
   actual stars/days that were granted, not the live policy values.
   This way an admin tweak later doesn't rewrite history.
3. Apply grants on both sides (atomic-ish: DB row first, then stars,
   then days). A grant failure mid-flow leaves the redemption row but
   the user can still re-trigger the grant via a reconciliation job
   (not built yet — log loudly when this happens).

Policy values live in `app_settings`:
  - referral_inviter_stars   (default 100)
  - referral_inviter_days    (default 7)
  - referral_invitee_stars   (default 30)
  - referral_invitee_days    (default 7)
"""

import logging
import random
import re
import string
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app_config.service import AppSettingsService
from auth.admin_service import AdminUserService
from quiz.repositories.user_points import UserPointsRepository
from referrals.dtos import (
    InviteeStatusDTO,
    MyReferralCodeDTO,
    ReferralPolicyDTO,
    RedemptionResultDTO,
)
from referrals.models import ReferralCode, ReferralRedemption

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

_CODE_FORMAT_RE = re.compile(r"^[A-Z]{3}\d{3}[A-Z]{2}$")


class ReferralService:
    def __init__(
        self,
        db: Session,
        app_settings: AppSettingsService,
        admin_user_service: AdminUserService,
        user_points_repo: UserPointsRepository,
    ):
        self.db = db
        self.app_settings = app_settings
        self.admin_user_service = admin_user_service
        self.user_points_repo = user_points_repo

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
            try:
                user = self.admin_user_service.get_user(r.invitee_id)
                display = user.username or self._mask_phone(user.phone)
                has_paid = bool(user.subscription_end) and user.plan and user.plan.upper() == "PRO"
            except Exception as e:
                # Don't fail the whole list just because Keycloak hiccupped
                # on one invitee — show a placeholder and move on.
                logger.warning("Failed to fetch invitee %s: %s", r.invitee_id, e)
                display = "—"
                has_paid = False
            out.append(
                InviteeStatusDTO(
                    invitee_id=r.invitee_id,
                    invitee_display_name=display,
                    redeemed_at=r.redeemed_at,
                    has_paid_subscription=has_paid,
                )
            )
        return out

    # ─── public writes ────────────────────────────────────────────────

    def redeem(self, invitee_id: UUID, code: str) -> RedemptionResultDTO:
        """Apply a code on behalf of `invitee_id`. Raises HTTPException
        with a user-friendly Russian detail on every business-rule fail
        so the UI can show it verbatim."""
        code = code.strip().upper()

        if not _CODE_FORMAT_RE.match(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный формат промокода",
            )

        owner = self.db.query(ReferralCode).filter(ReferralCode.code == code).first()
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Такой промокод не существует",
            )
        if owner.user_id == invitee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя вводить свой собственный код",
            )

        already_redeemed = (
            self.db.query(ReferralRedemption)
            .filter(ReferralRedemption.invitee_id == invitee_id)
            .first()
        )
        if already_redeemed is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ты уже использовал промокод. Один код на аккаунт.",
            )

        policy = self.get_policy()

        # Persist redemption FIRST with the policy snapshot. If grants
        # below fail partway we still have an audit trail of the intent
        # and the user can't double-redeem.
        redemption = ReferralRedemption(
            code_id=owner.user_id,
            inviter_id=owner.user_id,
            invitee_id=invitee_id,
            inviter_stars_granted=policy.inviter_stars,
            inviter_days_granted=policy.inviter_days,
            invitee_stars_granted=policy.invitee_stars,
            invitee_days_granted=policy.invitee_days,
        )
        self.db.add(redemption)
        self.db.flush()

        # Stars first — fastest, in-DB, can't fail unless DB is down.
        self.user_points_repo.add_points(invitee_id, policy.invitee_stars)
        self.user_points_repo.add_points(owner.user_id, policy.inviter_stars)

        # Pro days — touches Keycloak. Failure here is loud-logged; the
        # invitee/inviter row already exists so they can be made whole
        # by a one-off admin grant if it ever happens.
        try:
            self.admin_user_service.grant_pro_subscription(
                user_id=invitee_id, days=policy.invitee_days
            )
        except Exception as e:
            logger.exception(
                "Failed to grant invitee Pro days (redemption %s): %s",
                redemption.id,
                e,
            )
        try:
            self.admin_user_service.grant_pro_subscription(
                user_id=owner.user_id, days=policy.inviter_days
            )
        except Exception as e:
            logger.exception(
                "Failed to grant inviter Pro days (redemption %s): %s",
                redemption.id,
                e,
            )

        self.db.commit()

        return RedemptionResultDTO(
            inviter_id=owner.user_id,
            invitee_stars_granted=policy.invitee_stars,
            invitee_days_granted=policy.invitee_days,
            inviter_stars_granted=policy.inviter_stars,
            inviter_days_granted=policy.inviter_days,
        )

    # ─── internals ────────────────────────────────────────────────────

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

    @staticmethod
    def _mask_phone(phone: str | None) -> str:
        # Fallback when user hasn't set a username — show last 4 digits.
        if not phone:
            return "—"
        digits = "".join(c for c in phone if c.isdigit())
        return f"+…{digits[-4:]}" if len(digits) >= 4 else "—"
