"""POST /payments/android/verify — Google Play Billing subscription activation.

The Android app uses Google Play Billing (`in_app_purchase` Flutter package)
to charge the user. The plugin hands back a `purchaseToken` string; we
forward it here, ask the Google Play Developer API to validate it, and if
Google confirms an active auto-renewable subscription we flip the user's
plan to PRO via the existing `SubscriptionService.activate_subscription` path.

This is the Android counterpart to `/payments/apple/verify` — the verification
logic lives in `payments/android_iap.py`, mirroring `payments/apple_iap.py`.
"""

import hashlib
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_subscription_plan_service,
    get_subscription_service,
)
from api.routes.auth.routes import get_current_user
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.android_iap import AndroidIAPVerifier
from payments.models import Payment
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/android", tags=["User - Payments"])

# One verifier instance per process — stateless except for the cached
# service-account credentials (refreshed automatically on expiry).
_verifier = AndroidIAPVerifier()

# Fallback price if the PRO plan can't be read from the DB (KZT, gross — before
# Google's cut). Matches the Play Console product kz.aima.aima.pro.monthly.
_PRO_FALLBACK_PRICE = Decimal("4990")


def _record_google_payment(
    session: Session,
    plan_service: SubscriptionPlanService,
    user_id: str,
    product_id: str,
    purchase_token: str,
) -> None:
    """Record a verified Google Play purchase as a Payment row.

    Lets the admin panel show Google Billing purchases alongside FreedomPay
    (same `payments` table / analytics). Best-effort: a failure here must NOT
    break activation — PRO is already granted by the time we're called.

    Idempotent: order_id is derived from the purchase token, so repeated verify
    calls (app retries / restarts) don't create duplicate rows. The amount is
    gross (pre-Google-fee); exact payouts come later from Google's reports.
    """
    order_id = "gplay-" + hashlib.sha256(purchase_token.encode()).hexdigest()[:40]
    try:
        if session.query(Payment).filter(Payment.order_id == order_id).first():
            return  # already recorded this purchase

        amount = _PRO_FALLBACK_PRICE
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
                amount = Decimal(str(pro.price))
        except Exception:  # noqa: BLE001 — price lookup is best-effort
            logger.warning("Could not read PRO price; using fallback %s", amount)

        session.add(
            Payment(
                order_id=order_id,
                amount=amount,
                currency="KZT",
                status="paid",
                pg_payment_method="google_play",
                is_subscription_payment=True,
                subscription_plan="PRO",
                user_id=str(user_id),
                pg_status_desc=f"Google Play IAP: {product_id}",
            )
        )
        session.commit()
        logger.info("Recorded Google Play payment %s for user %s", order_id, user_id)
    except Exception:  # noqa: BLE001 — never fail verify because of bookkeeping
        session.rollback()
        logger.exception("Failed to record Google Play payment for user %s", user_id)


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
):
    """Validate a Google Play purchase token and, on success, activate PRO.

    Returns the latest user DTO so the client can refresh local state in
    one round trip (no separate `/me` call needed after purchase).
    """
    result = _verifier.verify(body.purchase_token, body.product_id)

    if not result.is_valid:
        logger.warning(
            "Google Play token rejected for user %s: product=%s error=%s",
            current_user.id,
            body.product_id,
            result.error,
        )
        raise HTTPException(status_code=400, detail="Purchase verification failed")

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

    # Token valid + currently within the paid period → activate PRO.
    updated_user = await subscription_service.activate_subscription(
        current_user, PlanType.PRO, months=1
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

    return AndroidVerifyOut(
        is_active=True,
        expires_at=(result.expires_at.isoformat() if result.expires_at else None),
        environment=result.environment,
        user=updated_user,
    )
