"""POST /payments/apple/notifications-v2 — Apple App Store Server Notifications V2.

Apple calls this endpoint for every subscription lifecycle event: renewals,
expirations, refunds, revocations. We use it to keep PRO access in sync
without waiting for the user to open the app.

Setup (App Store Connect → App → App Information → App Store Server Notifications):
  Production URL: https://backend-production-f2a1.up.railway.app/payments/apple/notifications-v2
  Sandbox URL:    same (environment is auto-detected from the notification payload)

Security: the entire payload is a JWS signed by Apple's Root CA G3 chain.
SignedDataVerifier performs cryptographic verification — no shared secret
needed, and no way to spoof without Apple's private key.

We always return HTTP 200, even on verification failure or errors.
Apple retries non-200 responses for up to 24 hours, creating noise for
genuinely bad payloads. Our own errors are logged and handled internally.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_subscription_plan_service,
    get_subscription_service,
    get_user_repository_keycloak,
)
from auth.dtos.users import UserQueryDTO
from auth.repositories.users import UserRepositoryInterface
from common.enums import PlanType
from payments.apple_iap import (
    APP_APPLE_ID,
    BUNDLE_ID,
    _APPLE_ROOT_CA_G3_PATH,
    _peek_jws_payload,
)
from payments.models import Payment
from subscription.event_log import log_subscription_event
from payments.apple_notification import record_notification
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService
from utils.monitoring import IAP_EVENT_COUNT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/apple", tags=["Webhooks"])

# Notification types that mean money came in — extend PRO + record payment.
_MONEY_IN = {"SUBSCRIBED", "DID_RENEW", "OFFER_REDEEMED"}
# Notification types that mean access should end — revoke PRO.
_REVOKE = {"EXPIRED", "REVOKE", "REFUND"}
# Billing issues — Apple is still retrying, do NOT revoke yet.
_WARN_ONLY = {"DID_FAIL_TO_RENEW", "GRACE_PERIOD_EXPIRED"}

_PRO_FALLBACK_PRICE = Decimal("4990")


def _renewal_order_id(transaction_id: str) -> str:
    """Stable order_id for a single Apple transaction.

    Uses transactionId (not originalTransactionId) so each billing event
    (initial purchase + every auto-renewal) gets its own Payment row,
    making recurring revenue visible in the Finance page.
    Idempotent on redelivery of the same notification.
    """
    return "apple-" + hashlib.sha256(transaction_id.encode()).hexdigest()[:40]


def _decode_notification(signed_payload: str):
    """Verify and decode an Apple S2S notification JWS.

    Tries the environment claimed in the (unverified) payload first,
    falls back to the other. Returns None on any failure.
    """
    try:
        from appstoreserverlibrary.models.Environment import Environment
        from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    except ImportError:
        logger.error("[apple_s2s] app-store-server-library not installed")
        return None

    if not _APPLE_ROOT_CA_G3_PATH.exists():
        logger.error("[apple_s2s] Apple Root CA G3 cert missing at %s", _APPLE_ROOT_CA_G3_PATH)
        return None

    root_cert = _APPLE_ROOT_CA_G3_PATH.read_bytes()

    # Peek at unverified payload to pick the right environment verifier.
    try:
        unverified = _peek_jws_payload(signed_payload)
        raw_env = (unverified.get("data") or {}).get("environment", "Sandbox")
        primary = Environment.PRODUCTION if raw_env == "Production" else Environment.SANDBOX
    except Exception:
        primary = Environment.PRODUCTION

    fallback = Environment.SANDBOX if primary == Environment.PRODUCTION else Environment.PRODUCTION

    for env in (primary, fallback):
        try:
            verifier = SignedDataVerifier(
                root_certificates=[root_cert],
                enable_online_checks=False,
                bundle_id=BUNDLE_ID,
                app_apple_id=APP_APPLE_ID,
                environment=env,
            )
            return verifier.verify_and_decode_notification(signed_payload)
        except Exception as exc:
            logger.debug("[apple_s2s] verify failed env=%s: %s", env, exc)

    logger.warning("[apple_s2s] notification failed verification in both environments")
    return None


def _user_for_original_tx(session: Session, original_tx_id: str) -> str | None:
    """Find the user_id that originally bought this Apple subscription.

    The first purchase went through POST /payments/apple/verify which wrote a
    Payment row with order_id derived from original_transaction_id. That row
    is our user→transaction binding.
    """
    order_id = "apple-" + hashlib.sha256(original_tx_id.encode()).hexdigest()[:40]
    try:
        row = session.query(Payment).filter(Payment.order_id == order_id).first()
        return str(row.user_id) if row and row.user_id else None
    except Exception:
        logger.exception("[apple_s2s] user lookup failed for tx=%s", original_tx_id[:16])
        return None


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_user(
    session: Session, original_tx_id: str, app_account_token: str
) -> str | None:
    """Map an Apple transaction to our user_id.

    Primary: the Payment row written by POST /payments/apple/verify (keyed by
    originalTransactionId). With the iOS client now retrying verify until it
    succeeds (ApplePurchaseProcessor), this row is reliably present.

    Fallback: `appAccountToken` — the UUID the app sets to the user_id at
    purchase time, which Apple echoes back in EVERY notification for this
    subscription. This closes the gap where a renewal/expiry/refund arrives
    before any /verify ever ran (bought offline, reinstall, first-verify
    network fail) — without it those events were silently dropped and the
    paying user lost PRO. No DB row is needed: the token rides every event.
    """
    existing = _user_for_original_tx(session, original_tx_id)
    if existing:
        return existing
    if app_account_token and _is_uuid(app_account_token):
        logger.info(
            "[apple_s2s] resolved user via appAccountToken (no /verify row yet)"
        )
        return app_account_token
    return None


def _pro_price(plan_service: SubscriptionPlanService) -> Decimal:
    try:
        pro = next(
            (p for p in plan_service.get_available_plans() if str(p.plan_type).upper().endswith("PRO")),
            None,
        )
        if pro is not None and pro.price:
            return Decimal(str(pro.price))
    except Exception:
        pass
    return _PRO_FALLBACK_PRICE


def _record_renewal(
    session: Session,
    plan_service: SubscriptionPlanService,
    user_id: str,
    transaction_id: str,
    product_id: str | None,
    ntype: str,
) -> None:
    """Idempotently write one Payment row for an Apple renewal/purchase event."""
    try:
        order_id = _renewal_order_id(transaction_id)
        if session.query(Payment).filter(Payment.order_id == order_id).first():
            return
        session.add(
            Payment(
                order_id=order_id,
                amount=_pro_price(plan_service),
                currency="KZT",
                status="paid",
                pg_payment_method="apple",
                is_subscription_payment=True,
                subscription_plan="PRO",
                user_id=user_id,
                pg_status_desc=f"Apple S2S: {ntype} {product_id or 'PRO'}",
            )
        )
        session.commit()
        logger.info("[apple_s2s] recorded payment %s for user %s (%s)", order_id, user_id, ntype)
    except Exception:
        session.rollback()
        logger.exception("[apple_s2s] failed to record renewal for user %s", user_id)


@router.post("/notifications-v2")
async def apple_notifications_v2(
    request: Request,
    session: Session = Depends(get_db_session),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    plan_service: SubscriptionPlanService = Depends(get_subscription_plan_service),
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
):
    """Receive Apple App Store Server Notifications V2.

    Called by Apple for every subscription lifecycle event. Always returns
    200 — Apple retries non-200 for 24 hours, creating noise.
    """
    try:
        body = await request.json()
        signed_payload = body.get("signedPayload", "")
    except Exception:
        logger.warning("[apple_s2s] could not parse request body")
        return {"ok": True}

    if not signed_payload:
        return {"ok": True}

    notification = _decode_notification(signed_payload)
    if notification is None:
        return {"ok": True}

    ntype = str(getattr(notification, "notificationType", "") or "")
    nsubtype = str(getattr(notification, "subtype", "") or "")
    uuid = str(getattr(notification, "notificationUUID", "") or "")

    logger.info("[apple_s2s] type=%s subtype=%s uuid=%s", ntype, nsubtype, uuid)

    # #4: store raw + dedup. Apple delivers at-least-once; a notificationUUID we
    # already recorded is skipped (the UNIQUE insert is the atomic dedup). The
    # raw JWS is kept for audit / replay analysis.
    if uuid and not record_notification(session, uuid, ntype, signed_payload):
        logger.info("[apple_s2s] duplicate notification uuid=%s — skipping", uuid)
        return {"ok": True}

    if ntype == "TEST":
        logger.info("[apple_s2s] test notification OK")
        return {"ok": True}

    data = getattr(notification, "data", None)
    if data is None:
        return {"ok": True}

    tx = getattr(data, "signedTransactionInfo", None)
    if tx is None:
        logger.warning("[apple_s2s] missing signedTransactionInfo type=%s", ntype)
        return {"ok": True}

    original_tx_id = str(getattr(tx, "originalTransactionId", "") or "")
    transaction_id = str(getattr(tx, "transactionId", "") or original_tx_id)
    product_id = str(getattr(tx, "productId", "") or "")
    app_account_token = str(getattr(tx, "appAccountToken", "") or "")
    expires_ms = getattr(tx, "expiresDate", None)
    expires_at = (
        datetime.fromtimestamp(expires_ms / 1000.0, tz=UTC)
        if expires_ms
        else None
    )

    if not original_tx_id:
        logger.warning("[apple_s2s] no originalTransactionId type=%s", ntype)
        return {"ok": True}

    user_id = _resolve_user(session, original_tx_id, app_account_token)
    if not user_id:
        logger.warning(
            "[apple_s2s] no user mapped for originalTx=%s type=%s — "
            "no /verify row and no appAccountToken",
            original_tx_id[:16],
            ntype,
        )
        return {"ok": True}

    if ntype in _WARN_ONLY:
        logger.warning(
            "[apple_s2s] billing issue for user=%s type=%s — Apple still retrying, not revoking",
            user_id,
            ntype,
        )
        return {"ok": True}

    if ntype in _REVOKE:
        try:
            user = users.get(UserQueryDTO(id=UUID(user_id)))
            subscription_service.revoke_subscription(user)
            logger.info("[apple_s2s] revoked PRO for user=%s type=%s", user_id, ntype)
            IAP_EVENT_COUNT.labels("apple", ntype).inc()
            log_subscription_event(
                session, platform="apple", event_type=ntype.lower(),
                status="success", user_id=user_id, product_id=product_id,
                transaction_id=transaction_id, detail=f"S2S {ntype}",
            )
        except Exception:
            logger.exception("[apple_s2s] revoke failed for user=%s", user_id)
            log_subscription_event(
                session, platform="apple", event_type=ntype.lower(),
                status="failed", user_id=user_id, transaction_id=transaction_id,
                detail=f"S2S {ntype} revoke failed",
            )
        return {"ok": True}

    if ntype in _MONEY_IN:
        _record_renewal(session, plan_service, user_id, transaction_id, product_id, ntype)
        try:
            user = users.get(UserQueryDTO(id=UUID(user_id)))
            await subscription_service.activate_subscription(
                user, PlanType.PRO, months=1, expires_at=expires_at
            )
            logger.info(
                "[apple_s2s] extended PRO for user=%s type=%s expires=%s",
                user_id, ntype, expires_at,
            )
            IAP_EVENT_COUNT.labels("apple", ntype).inc()
            log_subscription_event(
                session, platform="apple",
                event_type="renew" if ntype == "DID_RENEW" else "purchase",
                status="success", user_id=user_id, product_id=product_id,
                transaction_id=transaction_id,
                detail=f"S2S {ntype} expires={expires_at}",
            )
        except Exception:
            logger.exception("[apple_s2s] activate_subscription failed for user=%s", user_id)
            log_subscription_event(
                session, platform="apple", event_type="activate_failed",
                status="failed", user_id=user_id, transaction_id=transaction_id,
                detail=f"S2S {ntype} activate failed",
            )
        return {"ok": True}

    logger.info("[apple_s2s] unhandled type=%s subtype=%s user=%s", ntype, nsubtype, user_id)
    return {"ok": True}
