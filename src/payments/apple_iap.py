"""Apple In-App Purchase receipt verification.

Apple ships two ways to validate IAP receipts server-side:

  1. **Legacy verifyReceipt endpoint** (`/verifyReceipt`) — accepts the
     base64 receipt blob the app pulls off the device. Returns the full
     receipt history including auto-renewable info. Apple has marked
     this "deprecated" but explicitly says it will keep working — and
     for a small EdTech app on launch it's the path of least
     resistance: no JWT signing, no key management, no Apple Server
     Notifications setup required.

  2. **App Store Server API** (`/inApps/v1/...`) — modern path that
     uses signed JWT tokens and a `.p8` API key. Lower latency, finer-
     grained transactions, but ~3× the integration surface. We can
     migrate later (TECH_DEBT.md), v1 stays on the simpler endpoint.

Apple's documented quirk for the legacy endpoint: receipts that came
from a sandbox build may be sent to the production URL and Apple
responds with status code **21007**. The recommended pattern (Apple
docs, `verifyReceipt` overview) is "always try production first;
retry sandbox on 21007". That single fallback is the only thing
keeping store-review test purchases from failing in production.

Status codes we care about
--------------------------

  0       — receipt is valid
  21007   — sandbox receipt sent to production endpoint → retry sandbox
  21002   — malformed receipt
  21003   — receipt could not be authenticated
  21004   — shared secret mismatch
  21005   — receipt server temporarily unavailable
  21006   — receipt valid but subscription expired (still treat as
            "auth-fine, just not currently subscribed")

Anything else → opaque error, return False.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"

# Lift to env if/when we need a separate sandbox-shared-secret. Most
# small apps reuse a single secret; Apple only generates one
# "App-Specific Shared Secret" per app.
SHARED_SECRET_ENV = "APPLE_APP_SHARED_SECRET"


@dataclass(frozen=True)
class AppleVerifyResult:
    """Normalised verifier output. Avoids leaking Apple's raw JSON shape
    into the rest of the codebase — if we move to App Store Server API
    later, only this verifier changes, the route handler keeps reading
    the same field names."""

    is_valid: bool
    is_active_subscription: bool
    product_id: str | None
    expires_at: datetime | None
    original_transaction_id: str | None
    environment: str  # "Production" / "Sandbox"
    raw_status: int
    error: str | None = None


class AppleIAPVerifier:
    """Pure-stateless verifier — instantiate once, call verify many."""

    def __init__(
        self,
        shared_secret: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        # Allow explicit override for tests; default to env so production
        # and Railway never see the secret in code.
        self._shared_secret = shared_secret or os.getenv(SHARED_SECRET_ENV)
        if not self._shared_secret:
            logger.warning(
                "%s not set — verify() will reject every receipt. "
                "This is the right behaviour pre-launch (no IAP yet) "
                "but must be configured before App Store submission.",
                SHARED_SECRET_ENV,
            )
        self._timeout = timeout_seconds

    def verify(self, receipt_data: str) -> AppleVerifyResult:
        """Validate a base64-encoded Apple receipt.

        Returns an `AppleVerifyResult` with `is_valid=True` only when
        Apple returned status 0. `is_active_subscription=True` further
        narrows to "and the auto-renewable subscription is currently
        within its paid period", computed from `expires_date_ms`.
        """
        if not self._shared_secret:
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-1,
                error="APPLE_APP_SHARED_SECRET not configured",
            )

        # Diagnostic: receipt shape. 21002 from Apple usually means the
        # client sent either an empty string, a JWS transaction (StoreKit 2),
        # or base64 with bad padding. Log size + start/end so we can tell
        # which one we're hitting without dumping the entire blob (which is
        # PII-adjacent and noisy at ~5-30 KB per call).
        receipt_len = len(receipt_data) if receipt_data else 0
        preview_head = receipt_data[:32] if receipt_len else "<empty>"
        preview_tail = receipt_data[-16:] if receipt_len > 32 else ""
        looks_like_jws = receipt_data.count(".") == 2 if receipt_data else False
        logger.info(
            "[apple_iap] receipt_data len=%d head=%r tail=%r jws_shape=%s",
            receipt_len,
            preview_head,
            preview_tail,
            looks_like_jws,
        )

        # Try production first — this is what Apple recommends in the
        # `verifyReceipt` docs. 21007 → fall back to sandbox.
        prod_result = self._call_endpoint(PRODUCTION_URL, receipt_data)
        if prod_result.raw_status == 21007:
            logger.info("Receipt is from sandbox; retrying against sandbox endpoint")
            return self._call_endpoint(SANDBOX_URL, receipt_data)
        return prod_result

    def _call_endpoint(self, url: str, receipt_data: str) -> AppleVerifyResult:
        try:
            response = requests.post(
                url,
                json={
                    "receipt-data": receipt_data,
                    "password": self._shared_secret,
                    # exclude-old-transactions trims the response payload
                    # to only the most recent receipt per product id —
                    # we don't need history for activation, only the
                    # latest expiry.
                    "exclude-old-transactions": True,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.exception("Apple verifyReceipt network error: %s", exc)
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-2,
                error=f"network: {exc.__class__.__name__}",
            )

        if response.status_code != 200:
            logger.error(
                "Apple verifyReceipt HTTP %s: %s",
                response.status_code,
                response.text[:200],
            )
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-3,
                error=f"http {response.status_code}",
            )

        payload = response.json()
        status = int(payload.get("status", -1))
        environment = payload.get("environment", "unknown")

        if status != 0 and status != 21006:
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment=environment,
                raw_status=status,
                error=f"apple status {status}",
            )

        # 0 = valid receipt. 21006 = valid receipt but subscription
        # expired (legacy endpoint quirk for non-renewable receipts).
        # Both mean the receipt itself is authentic — only
        # `is_active_subscription` differs.
        latest = payload.get("latest_receipt_info") or []
        if not latest:
            # Receipt is authentic but contains no subscription info
            # (no IAP made yet). Treat as valid-but-inactive so the
            # caller can distinguish "user is logged in to App Store but
            # has never bought" from "fraud".
            return AppleVerifyResult(
                is_valid=True,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment=environment,
                raw_status=status,
            )

        # Pick the latest-expiring transaction. exclude-old-transactions
        # already trimmed the noise; we just sort by expires_date_ms
        # for safety.
        latest_sorted = sorted(
            latest,
            key=lambda t: int(t.get("expires_date_ms", 0)),
            reverse=True,
        )
        most_recent = latest_sorted[0]
        expires_ms = int(most_recent.get("expires_date_ms", 0))
        expires_at = (
            datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
            if expires_ms
            else None
        )
        is_active = bool(expires_at and expires_at > datetime.now(timezone.utc))
        return AppleVerifyResult(
            is_valid=True,
            is_active_subscription=is_active,
            product_id=most_recent.get("product_id"),
            expires_at=expires_at,
            original_transaction_id=most_recent.get("original_transaction_id"),
            environment=environment,
            raw_status=status,
        )
