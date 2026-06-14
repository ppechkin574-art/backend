"""POST /payments/android/verify — Google Play Billing subscription activation.

The Android app uses Google Play Billing (`in_app_purchase` Flutter package)
to charge the user. The plugin hands back a `purchaseToken` string; we
forward it here, ask the Google Play Developer API to validate it, and if
Google confirms an active auto-renewable subscription we flip the user's
plan to PRO via the existing `SubscriptionService.activate_subscription` path.

This is the Android counterpart to `/payments/apple/verify` — the verification
logic lives in `payments/android_iap.py`, mirroring `payments/apple_iap.py`.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import (
    get_admin_user_service,
    get_db_session,
    get_subscription_plan_service,
    get_subscription_service,
    get_user_repository_keycloak,
)
from api.routes.auth.routes import get_current_user
from auth.admin_service import AdminUserService
from auth.dtos.users import UserDTO, UserQueryDTO
from auth.repositories.users import UserRepositoryInterface
from common.enums import PlanType
from payments.android_iap import AndroidIAPVerifier
from payments.models import Payment
from quiz.repositories.user_points import UserPointsRepository
from referrals.service import grant_pending_invitee_reward
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

# The only Google Play products that unlock PRO. product_id arrives from the
# client, so it must be checked against this allow-list before activation.
_DEFAULT_PRODUCT_ID = "kz.aima.aima.pro.monthly"
_ALLOWED_PRODUCT_IDS = {_DEFAULT_PRODUCT_ID}

router = APIRouter(prefix="/payments/android", tags=["User - Payments"])

# One verifier instance per process — stateless except for the cached
# service-account credentials (refreshed automatically on expiry).
_verifier = AndroidIAPVerifier()

# Fallback price if the PRO plan can't be read from the DB (KZT, gross — before
# Google's cut). Matches the Play Console product kz.aima.aima.pro.monthly.
_PRO_FALLBACK_PRICE = Decimal("4990")


def _pro_price(plan_service: SubscriptionPlanService) -> Decimal:
    """PRO plan price from the DB, or the fallback. Best-effort."""
    try:
        pro = next(
            (
                p
                for p in plan_service.get_available_plans()
                if str(p.plan_type).upper().endswith("PRO")
            ),
            None,
        )
        if pro is not None and pro.price:
            return Decimal(str(pro.price))
    except Exception:  # noqa: BLE001 — price lookup is best-effort
        logger.warning("Could not read PRO price; using fallback %s", _PRO_FALLBACK_PRICE)
    return _PRO_FALLBACK_PRICE


def _insert_google_payment(
    session: Session,
    plan_service: SubscriptionPlanService,
    order_id: str,
    user_id: str,
    product_id: str,
    desc: str,
) -> None:
    """Idempotently insert a paid Google Play Payment row.

    Best-effort: any failure is swallowed (never breaks the caller). Idempotent
    on order_id, so repeated verify/RTDN deliveries don't create duplicates.
    Amount is gross (pre-Google-fee); exact payouts come from Google's reports.
    """
    try:
        if session.query(Payment).filter(Payment.order_id == order_id).first():
            return  # already recorded
        session.add(
            Payment(
                order_id=order_id,
                amount=_pro_price(plan_service),
                currency="KZT",
                status="paid",
                pg_payment_method="google_play",
                is_subscription_payment=True,
                subscription_plan="PRO",
                user_id=str(user_id),
                pg_status_desc=desc,
            )
        )
        session.commit()
        logger.info("Recorded Google Play payment %s for user %s", order_id, user_id)
    except Exception:  # noqa: BLE001 — bookkeeping must never break the caller
        session.rollback()
        logger.exception("Failed to record Google Play payment for user %s", user_id)


def _token_order_id(purchase_token: str) -> str:
    """Stable order_id derived from the Google purchase token.

    The same token maps to the same row across the initial verify and every
    RTDN renewal (Play keeps the token stable for a subscription), so this also
    binds the token to one account. Single source of truth for the derivation.
    """
    return "gplay-" + hashlib.sha256(purchase_token.encode()).hexdigest()[:40]


def _token_owner(session: Session, purchase_token: str) -> str | None:
    """Return the user_id that first verified this token, or None if unseen.

    Used to reject replay of one purchase token across multiple accounts: the
    initial verify records a Payment whose order_id is derived from the token,
    binding the purchase to that first account.
    """
    try:
        row = (
            session.query(Payment)
            .filter(Payment.order_id == _token_order_id(purchase_token))
            .first()
        )
        return str(row.user_id) if row and row.user_id else None
    except Exception:  # noqa: BLE001 — a lookup hiccup must not block a real buyer
        logger.exception("token-owner lookup failed")
        return None


def _record_google_payment(
    session: Session,
    plan_service: SubscriptionPlanService,
    user_id: str,
    product_id: str,
    purchase_token: str,
) -> None:
    """Record the INITIAL verified purchase (order_id derived from the token)."""
    _insert_google_payment(
        session,
        plan_service,
        _token_order_id(purchase_token),
        user_id,
        product_id,
        f"Google Play IAP: {product_id}",
    )


def _revoke_pro_for_token(
    db_session: Session,
    users: "UserRepositoryInterface",
    subscription_service: "SubscriptionService",
    purchase_token: str,
    reason: str,
) -> None:
    """Map a purchase token to its owner and immediately strip PRO.

    Used for refund/chargeback (voided) and Google REVOKED/EXPIRED RTDN events,
    so a user who got their money back no longer keeps PRO. Best-effort.
    """
    if not purchase_token:
        return
    try:
        owner_id = _token_owner(db_session, purchase_token)
        if not owner_id:
            logger.warning("RTDN revoke: no user mapped for token (%s)", reason)
            return
        user = users.get(UserQueryDTO(id=UUID(str(owner_id))))
        subscription_service.revoke_subscription(user)
        logger.info("RTDN revoke: PRO stripped for user %s (%s)", owner_id, reason)
    except Exception:  # noqa: BLE001 — must not 500 the Pub/Sub push
        logger.exception("RTDN revoke failed (%s)", reason)


class AndroidVerifyIn(BaseModel):
    purchase_token: str
    product_id: str


class AndroidVerifyOut(BaseModel):
    is_active: bool
    expires_at: str | None
    environment: str  # "Production" | "Sandbox"
    user: UserDTO


@router.post("/verify", response_model=AndroidVerifyOut)
async def verify_android_purchase(
    body: AndroidVerifyIn,
    current_user: UserDTO = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    db_session: Session = Depends(get_db_session),
    plan_service: SubscriptionPlanService = Depends(get_subscription_plan_service),
    admin_user_service: AdminUserService = Depends(get_admin_user_service),
):
    """Validate a Google Play purchase token and, on success, activate PRO.

    Returns the latest user DTO so the client can refresh local state in
    one round trip (no separate `/me` call needed after purchase).
    """
    # Only our own PRO product unlocks PRO. The product_id is client-supplied;
    # without this an unrelated/cheaper SKU that happens to be active could be
    # used to grant PRO.
    if body.product_id not in _ALLOWED_PRODUCT_IDS:
        logger.warning(
            "Google Play verify rejected: unknown product_id=%s (user %s)",
            body.product_id,
            current_user.id,
        )
        raise HTTPException(status_code=400, detail="Unknown product")

    result = _verifier.verify(body.purchase_token, body.product_id)

    if not result.is_valid:
        logger.warning(
            "Google Play token rejected for user %s: product=%s error=%s",
            current_user.id,
            body.product_id,
            result.error,
        )
        raise HTTPException(status_code=400, detail="Purchase verification failed")

    # Bind the purchase to the first account that verified it. A single Google
    # purchase token must not unlock PRO on many accounts (token sharing/replay).
    existing_owner = _token_owner(db_session, body.purchase_token)
    if existing_owner is not None and existing_owner != str(current_user.id):
        logger.warning(
            "Google Play token replay: already linked to %s, rejected for %s",
            existing_owner,
            current_user.id,
        )
        raise HTTPException(
            status_code=409,
            detail="This purchase is already linked to another account",
        )

    if not result.is_active_subscription:
        # Token is authentic but subscription has already expired or
        # payment is still pending. Don't activate; let the client decide.
        logger.info(
            "Google Play token valid but subscription not active for user %s: product=%s",
            current_user.id,
            body.product_id,
        )
        return AndroidVerifyOut(
            is_active=False,
            expires_at=(result.expires_at.isoformat() if result.expires_at else None),
            environment=result.environment,
            user=current_user,
        )

    # Token valid + currently within the paid period → activate PRO. Use
    # Google's authoritative expiry so the PRO period matches what was actually
    # bought (monthly, annual, trial, grace) instead of a hardcoded 30 days.
    updated_user = await subscription_service.activate_subscription(
        current_user,
        PlanType.PRO,
        months=1,
        expires_at=result.expires_at,
    )

    # Record the purchase so it shows up in the admin panel next to FreedomPay.
    # Best-effort — never blocks activation (PRO is already granted above).
    _record_google_payment(
        db_session, plan_service, str(current_user.id), body.product_id, body.purchase_token
    )

    logger.info(
        "Google Play IAP activated PRO for user %s: product=%s expires=%s env=%s",
        current_user.id,
        body.product_id,
        result.expires_at,
        result.environment,
    )

    # Grant deferred referral reward if this is the invitee's first real payment.
    try:
        grant_pending_invitee_reward(
            user_id=current_user.id,
            db=db_session,
            user_points_repo=UserPointsRepository(db_session),
            admin_user_service=admin_user_service,
        )
        db_session.commit()
    except Exception:
        logger.exception("Referral reward grant failed for user %s (Android IAP)", current_user.id)

    return AndroidVerifyOut(
        is_active=True,
        expires_at=(result.expires_at.isoformat() if result.expires_at else None),
        environment=result.environment,
        user=updated_user,
    )


# Google subscription notificationType → label. "Money-in" types record a
# renewal/purchase payment so recurring revenue shows in the admin panel.
_RTDN_TYPES = {
    1: "RECOVERED",
    2: "RENEWED",
    3: "CANCELED",
    4: "PURCHASED",
    5: "ON_HOLD",
    6: "IN_GRACE_PERIOD",
    7: "RESTARTED",
    8: "PRICE_CHANGE_CONFIRMED",
    9: "DEFERRED",
    10: "PAUSED",
    11: "PAUSE_SCHEDULE_CHANGED",
    12: "REVOKED",
    13: "EXPIRED",
}
_RTDN_MONEY_IN = {1, 2, 4, 7}  # RECOVERED, RENEWED, PURCHASED, RESTARTED
_RTDN_REVOKE = {12, 13}  # REVOKED, EXPIRED → strip PRO now (CANCELED=3 keeps
#                          access until period end, so it is NOT revoked here)


@router.post("/rtdn")
async def google_rtdn(
    request: Request,
    token: str = Query(default=""),
    x_rtdn_secret: str = Header(default=""),
    db_session: Session = Depends(get_db_session),
    plan_service: SubscriptionPlanService = Depends(get_subscription_plan_service),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
):
    """Real-time Developer Notifications from Google Play (via Pub/Sub push).

    Captures the subscription lifecycle (renewals, cancels, refunds): renewals
    extend PRO, refund/REVOKED/EXPIRED strip it, all mapped to our user via the
    original purchase Payment.

    Security: shared secret, preferred in the `X-RTDN-Secret` header (kept out of
    URLs/logs); the `?token=` query param is still accepted for the current
    Pub/Sub push config. Set GOOGLE_RTDN_SECRET in Railway. Compared in constant
    time.

    Always returns 200 so Pub/Sub doesn't retry on our bookkeeping hiccups.
    """
    secret = os.getenv("GOOGLE_RTDN_SECRET", "")
    provided = x_rtdn_secret or token
    if not secret or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        envelope = await request.json()
        data_b64 = (envelope.get("message") or {}).get("data")
        if not data_b64:
            return {"ok": True}  # Pub/Sub verification / empty message
        notif = json.loads(base64.b64decode(data_b64).decode())
    except Exception:  # noqa: BLE001 — malformed push must not 500 (Pub/Sub retries)
        logger.warning("RTDN: could not decode notification payload")
        return {"ok": True}

    voided = notif.get("voidedPurchaseNotification")
    if voided:
        # Refund / chargeback → strip PRO (money was returned).
        token = str(voided.get("purchaseToken", ""))
        logger.info(
            "RTDN voided/refund: orderId=%s token=%s",
            voided.get("orderId"),
            token[:16],
        )
        _revoke_pro_for_token(
            db_session, users, subscription_service, token, "refund/void"
        )
        return {"ok": True}

    sub = notif.get("subscriptionNotification")
    if not sub:
        logger.info("RTDN non-subscription notification keys=%s", list(notif.keys()))
        return {"ok": True}

    ntype = sub.get("notificationType")
    product_id = sub.get("subscriptionId") or "kz.aima.aima.pro.monthly"
    purchase_token = sub.get("purchaseToken", "")
    logger.info(
        "RTDN subscription: type=%s(%s) product=%s token=%s",
        ntype,
        _RTDN_TYPES.get(ntype, "?"),
        product_id,
        purchase_token[:16],
    )

    if ntype in _RTDN_REVOKE and purchase_token:
        # REVOKED (refund) / EXPIRED → take PRO away now.
        _revoke_pro_for_token(
            db_session,
            users,
            subscription_service,
            purchase_token,
            _RTDN_TYPES.get(ntype, str(ntype)),
        )
        return {"ok": True}

    if ntype in _RTDN_MONEY_IN and purchase_token:
        # Map back to our user via the original purchase row (the purchase token
        # stays the same across renewals for Play subscriptions).
        token_hash = hashlib.sha256(purchase_token.encode()).hexdigest()
        original = (
            db_session.query(Payment)
            .filter(Payment.order_id == "gplay-" + token_hash[:40])
            .first()
        )
        if not original or not original.user_id:
            logger.warning("RTDN: no user mapped for token (no original Payment), type=%s", ntype)
            return {"ok": True}

        event_ms = str(notif.get("eventTimeMillis", "0"))
        # Unique per event so each renewal is its own row (idempotent on redelivery).
        order_id = f"gplay-evt-{token_hash[:24]}-{event_ms}"
        _insert_google_payment(
            db_session,
            plan_service,
            order_id,
            original.user_id,
            product_id,
            f"Google Play RTDN: {_RTDN_TYPES.get(ntype, ntype)}",
        )

        # Extend PRO on renewal. Without this the user's subscription_end (set
        # to ~1 month at the first purchase) lapses and the backend
        # auto-downgrades to FREE — even though Google keeps charging. Re-verify
        # the token (the renewal keeps the same token) and, while it's active,
        # re-activate PRO so subscription_end moves forward. Best-effort: never
        # break the 200 response.
        try:
            result = _verifier.verify(purchase_token, product_id)
            if result.is_valid and result.is_active_subscription:
                user = users.get(UserQueryDTO(id=UUID(str(original.user_id))))
                await subscription_service.activate_subscription(
                    user,
                    PlanType.PRO,
                    months=1,
                    expires_at=result.expires_at,
                )
                logger.info(
                    "RTDN: extended PRO for user %s (type=%s)", original.user_id, ntype
                )
            else:
                logger.info(
                    "RTDN: token not active on renewal for user %s (type=%s)",
                    original.user_id,
                    ntype,
                )
        except Exception:  # noqa: BLE001 — entitlement sync must not 500 the push
            logger.exception(
                "RTDN: failed to extend PRO for user %s", original.user_id
            )

    return {"ok": True}
