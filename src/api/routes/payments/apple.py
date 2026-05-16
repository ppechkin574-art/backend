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

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_subscription_service
from api.routes.auth.routes import get_current_user
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.apple_iap import AppleIAPVerifier
from pydantic import BaseModel
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/apple", tags=["User - Payments"])

# One verifier instance per process — it's stateless (just holds the
# shared secret + timeout).
_verifier = AppleIAPVerifier()


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
