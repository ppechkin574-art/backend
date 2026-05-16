"""POST /payments/android/verify — Google Play Billing subscription activation.

The Android app uses Google Play Billing (`in_app_purchase` Flutter package)
to charge the user. The plugin hands back a `purchaseToken` string; we
forward it here, ask the Google Play Developer API to validate it, and if
Google confirms an active auto-renewable subscription we flip the user's
plan to PRO via the existing `SubscriptionService.activate_subscription` path.

This is the Android counterpart to `/payments/apple/verify` — the verification
logic lives in `payments/android_iap.py`, mirroring `payments/apple_iap.py`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_subscription_service
from api.routes.auth.routes import get_current_user
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.android_iap import AndroidIAPVerifier
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/android", tags=["User - Payments"])

# One verifier instance per process — stateless except for the cached
# service-account credentials (refreshed automatically on expiry).
_verifier = AndroidIAPVerifier()


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
