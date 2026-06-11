"""POST /payments/apple/verify — Apple In-App Purchase activation.

The iOS app uses StoreKit (`in_app_purchase` Flutter package) to charge
the user. StoreKit hands back a base64 receipt; we forward it here, ask
Apple to validate it, and if Apple confirms an active auto-renewable
subscription we flip the user's plan to PRO via the existing
`SubscriptionService.activate_subscription` path.

This is the iOS-only counterpart to FreedomPay (`/payments/create`) —
Android keeps the FreedomPay flow because Apple's IAP is mandatory only
inside iOS apps (App Store guideline 3.1.1).
"""

import hashlib
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_subscription_plan_service,
    get_subscription_service,
)
from api.routes.auth.routes import get_current_user
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.apple_iap import AppleIAPVerifier
from payments.models import Payment
from pydantic import BaseModel
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/apple", tags=["User - Payments"])

# One verifier instance per process — it's stateless (just holds the
# shared secret + timeout).
_verifier = AppleIAPVerifier()

# Fallback price if the PRO plan can't be read from the DB (KZT, gross — before
# Apple's cut). Mirrors the Google flow's _PRO_FALLBACK_PRICE so both stores
# record the same gross plan price; the net cut is applied later in analytics.
_PRO_FALLBACK_PRICE = Decimal("4990")


def _pro_price(plan_service: SubscriptionPlanService) -> Decimal:
    """PRO plan price from the DB, or the fallback. Best-effort.

    Replicated from the Google flow (`payments/android.py`) so the Apple route
    stays independent of the Android module — both record the same gross price.
    """
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


def _apple_order_id(transaction_id: str) -> str:
    """Stable order_id derived from the Apple transaction id.

    Prefer the original_transaction_id (kept stable across auto-renewals), so a
    renewal or a repeat verify of the same subscription maps to the SAME row —
    making the insert idempotent. Mirrors the Google flow's token-derived id.
    """
    return "apple-" + hashlib.sha256(transaction_id.encode()).hexdigest()[:40]


def _record_apple_payment(
    session: Session,
    plan_service: SubscriptionPlanService,
    user_id: str,
    transaction_id: str,
    product_id: str | None,
) -> None:
    """Idempotently insert a paid Apple IAP Payment row.

    Best-effort: any failure is swallowed (never breaks receipt verification or
    subscription activation, which already happened by the time this runs).
    Idempotent on order_id (derived from the stable transaction id), so repeated
    verify/restore calls and renewals don't create duplicates. Amount is gross
    (pre-Apple-fee); the store commission is netted out in analytics.
    """
    try:
        order_id = _apple_order_id(transaction_id)
        if session.query(Payment).filter(Payment.order_id == order_id).first():
            return  # already recorded
        session.add(
            Payment(
                order_id=order_id,
                amount=_pro_price(plan_service),
                currency="KZT",
                status="paid",
                pg_payment_method="apple",
                is_subscription_payment=True,
                subscription_plan="PRO",
                user_id=str(user_id),
                pg_status_desc=f"Apple IAP: {product_id or 'PRO'}",
            )
        )
        session.commit()
        logger.info("Recorded Apple payment %s for user %s", order_id, user_id)
    except Exception:  # noqa: BLE001 — bookkeeping must never break the caller
        session.rollback()
        logger.exception("Failed to record Apple payment for user %s", user_id)


class AppleVerifyIn(BaseModel):
    receipt_data: str


class AppleVerifyOut(BaseModel):
    is_active: bool
    product_id: str | None
    expires_at: str | None
    environment: str
    user: UserDTO


@router.post("/verify", response_model=AppleVerifyOut)
async def verify_apple_receipt(
    body: AppleVerifyIn,
    current_user: UserDTO = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    db_session: Session = Depends(get_db_session),
    plan_service: SubscriptionPlanService = Depends(get_subscription_plan_service),
):
    """Validate the StoreKit receipt and, on success, activate PRO.

    Returns the latest user DTO so the client can refresh local state in
    one round trip (no separate `/me` call needed after purchase).
    """
    result = _verifier.verify(body.receipt_data)

    if not result.is_valid:
        # Authentication failed at Apple's side — could be malformed,
        # wrong shared secret, or fraud. The verifier already logged the
        # detail; surface a generic 400 to the client.
        logger.warning(
            "Apple receipt rejected for user %s: status=%s error=%s",
            current_user.id,
            result.raw_status,
            result.error,
        )
        raise HTTPException(status_code=400, detail="Receipt verification failed")

    if not result.is_active_subscription:
        # Receipt is authentic but no active sub (status 21006 or empty
        # latest_receipt_info). This happens when StoreKit hands back a
        # stale receipt — e.g. user restored on a fresh device but
        # subscription has lapsed. Don't activate; let the client decide
        # whether to prompt for purchase.
        logger.info(
            "Apple receipt valid but no active subscription for user %s",
            current_user.id,
        )
        return AppleVerifyOut(
            is_active=False,
            product_id=result.product_id,
            expires_at=(result.expires_at.isoformat() if result.expires_at else None),
            environment=result.environment,
            user=current_user,
        )

    # Receipt valid + currently in the paid period → mirror Apple's expiry
    # date. We pass `expires_at` from the receipt instead of `months=1` so
    # restore-purchases doesn't silently add 30 days on top of remaining
    # time (see SubscriptionService.activate_subscription docstring + tests).
    # Apple's `expiresDate` is the source of truth — they already know when
    # the subscription will renew or lapse; our DB is just a cache.
    updated_user = await subscription_service.activate_subscription(
        current_user, PlanType.PRO, expires_at=result.expires_at
    )

    # Record the purchase so Apple revenue shows up in the admin panel.
    # Prefer original_transaction_id (stable across renewals); fall back to a
    # SHA-256 of the receipt so we always get a row even when Apple omits the
    # transaction id (rare with legacy SK1 receipts). Idempotent — same input
    # always produces the same order_id, so repeated /verify calls don't
    # create duplicates.
    tx_id = result.original_transaction_id or hashlib.sha256(
        body.receipt_data.encode()
    ).hexdigest()[:40]
    _record_apple_payment(
        db_session,
        plan_service,
        str(current_user.id),
        tx_id,
        result.product_id,
    )

    logger.info(
        "Apple IAP activated PRO for user %s: product=%s tx=%s expires=%s env=%s",
        current_user.id,
        result.product_id,
        result.original_transaction_id,
        result.expires_at,
        result.environment,
    )

    return AppleVerifyOut(
        is_active=True,
        product_id=result.product_id,
        expires_at=(result.expires_at.isoformat() if result.expires_at else None),
        environment=result.environment,
        user=updated_user,
    )
