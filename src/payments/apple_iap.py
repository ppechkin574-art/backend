"""Apple In-App Purchase receipt verification.

We accept TWO receipt formats from the iOS client:

  1. **Legacy base64 receipt blob** (StoreKit 1, what `appStoreReceiptURL`
     produces). Validated via the deprecated-but-still-supported
     `/verifyReceipt` endpoint.

  2. **JWS signed transaction** (StoreKit 2, what
     `in_app_purchase_storekit` returns for restored purchases on iOS
     18+). Validated locally with Apple's `app-store-server-library`
     using the Apple Root CA G3 bundled in this directory — no network
     call to Apple needed for verification, signature crypto plus the
     cert chain is enough.

Detection is shape-based: a JWS is two dots `.` joining three base64url
segments (`header.payload.signature`). Anything else we treat as a
legacy receipt and send to `/verifyReceipt`.

The StoreKit 2 path lets us accept Restore Purchases events on modern
iOS without forcing the client to downgrade — and the client side has
no clean way to ask the plugin for a SK1 receipt once Apple has moved
the device to SK2. So the fix lives here.

`app-store-server-library` is imported lazily inside the JWS branch so
a) the legacy path stays runnable if the dep is somehow missing, and
b) startup doesn't pay the import cost when no JWS receipt ever
arrives.

Status codes we care about (legacy path)
----------------------------------------

  0       — receipt is valid
  21007   — sandbox receipt sent to production endpoint → retry sandbox
  21002   — malformed receipt (we still log it, but JWS shape is
            handled BEFORE this can fire)
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
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"

# Lift to env if/when we need a separate sandbox-shared-secret. Most
# small apps reuse a single secret; Apple only generates one
# "App-Specific Shared Secret" per app.
SHARED_SECRET_ENV = "APPLE_APP_SHARED_SECRET"

# App identity used by the StoreKit 2 verifier to bind the receipt to
# our app. Lifted from environment so we don't hardcode bundle IDs the
# admin/ops side might want to override in a clone-of-prod test
# environment, but the defaults match our current ASC entries.
BUNDLE_ID = os.getenv("APPLE_BUNDLE_ID", "kz.aima.aima")
APP_APPLE_ID = int(os.getenv("APPLE_APP_ID", "6766537009"))

# Apple Root CA G3 — the root that signs the StoreKit 2 leaf cert
# chain (`x5c` header). Bundled here so verification works offline.
# Re-download from https://www.apple.com/certificateauthority/AppleRootCA-G3.cer
# when Apple rotates (rare; last issued 2014, valid through 2039).
_APPLE_ROOT_CA_G3_PATH = Path(__file__).parent / "apple_root_ca_g3.cer"


def _looks_like_jws(receipt_data: str | None) -> bool:
    """JWS is `header.payload.signature` — three base64url segments
    joined by two dots. Legacy `appStoreReceiptURL` base64 receipts have
    no dots. This cheap shape check is enough to route between paths
    before either side touches crypto."""
    if not receipt_data:
        return False
    return receipt_data.count(".") == 2


def _peek_jws_payload(jws: str) -> dict:
    """Decode the JWS payload WITHOUT signature verification. Used only
    to read the `environment` claim before we instantiate the right
    SignedDataVerifier — the verifier itself does the signed read."""
    import base64
    import json

    _, payload_b64, _ = jws.split(".")
    # base64url decoding tolerant of stripped padding
    payload_b64 += "=" * (-len(payload_b64) % 4)
    raw = base64.urlsafe_b64decode(payload_b64)
    return json.loads(raw)


def _env_from_claim(claim: str | None) -> str:
    """Normalise Apple's environment claim to the two values we care
    about. Apple sometimes uses 'Sandbox' / 'Production'; on rare
    StoreKit testing modes ('Xcode', 'LocalTesting') we conservatively
    treat them as Sandbox so the verifier doesn't reject them."""
    if claim == "Production":
        return "Production"
    return "Sandbox"


def _other_env(env: str) -> str:
    return "Sandbox" if env == "Production" else "Production"


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

        # Receipt shape branching: a JWS is `header.payload.signature`,
        # three base64url segments. We log size + start/end + the shape
        # flag so a future 21002 (or analogous JWS failure) is one log
        # line away from a diagnosis. Receipt itself stays out of logs —
        # PII-adjacent and 5-30 KB per call.
        receipt_len = len(receipt_data) if receipt_data else 0
        preview_head = receipt_data[:32] if receipt_len else "<empty>"
        preview_tail = receipt_data[-16:] if receipt_len > 32 else ""
        looks_like_jws = _looks_like_jws(receipt_data)
        logger.info(
            "[apple_iap] receipt_data len=%d head=%r tail=%r jws_shape=%s",
            receipt_len,
            preview_head,
            preview_tail,
            looks_like_jws,
        )

        if looks_like_jws:
            return self._verify_jws(receipt_data)

        # Legacy base64 receipt → /verifyReceipt. Try production first
        # per Apple's docs, retry sandbox on 21007.
        prod_result = self._call_endpoint(PRODUCTION_URL, receipt_data)
        if prod_result.raw_status == 21007:
            logger.info("Receipt is from sandbox; retrying against sandbox endpoint")
            return self._call_endpoint(SANDBOX_URL, receipt_data)
        return prod_result

    def _verify_jws(self, signed_transaction: str) -> AppleVerifyResult:
        """Verify a StoreKit 2 signed transaction locally using Apple's
        Root CA G3 + the x5c chain embedded in the JWS header. No HTTP
        call to Apple — signature cryptography plus the cert chain is a
        complete proof that this transaction was issued for our bundle
        id on our App Store account.

        Apple's `SignedDataVerifier` is environment-specific (Production
        vs Sandbox); the JWS payload itself carries the environment so
        we peek at it first, then build the verifier against the right
        env. Falls back to the other env on signature failure to
        gracefully handle iOS reporting one environment while the
        receipt was actually issued from the other.
        """
        try:
            unverified_payload = _peek_jws_payload(signed_transaction)
        except Exception as e:
            logger.exception("[apple_iap] failed to peek JWS payload: %s", e)
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-3,
                error=f"jws_peek: {e.__class__.__name__}",
            )

        # Environment claim in JWS payload — "Sandbox" / "Production".
        # Default to Sandbox so TestFlight builds verify even if Apple
        # ever omits the claim.
        env_claim = unverified_payload.get("environment", "Sandbox")

        # Try claimed env first; on failure try the other (catches
        # environment-claim-vs-signing-key mismatches Apple has shipped
        # in the past).
        primary = _env_from_claim(env_claim)
        fallback = _other_env(primary)

        result = self._verify_jws_one_env(signed_transaction, primary)
        if result.is_valid:
            return result
        logger.info(
            "[apple_iap] JWS verification failed in %s, retrying %s",
            primary,
            fallback,
        )
        return self._verify_jws_one_env(signed_transaction, fallback)

    def _verify_jws_one_env(self, signed_transaction: str, environment_name: str) -> AppleVerifyResult:
        """Single-env verification attempt. Returns failure with
        env-specific raw_status so the caller can tell prod-fail apart
        from sandbox-fail."""
        try:
            # Lazy imports — keep startup cheap when no JWS receipt
            # ever arrives, and avoid an import-time crash if the dep
            # is missing on an older replica.
            from appstoreserverlibrary.signed_data_verifier import (  # noqa: PLC0415
                SignedDataVerifier,
            )
            from appstoreserverlibrary.models.Environment import (  # noqa: PLC0415
                Environment,
            )
        except ImportError as e:
            logger.error("[apple_iap] app-store-server-library not installed: %s", e)
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-4,
                error=f"jws_lib_missing: {e}",
            )

        if not _APPLE_ROOT_CA_G3_PATH.exists():
            logger.error(
                "[apple_iap] Apple Root CA G3 file missing at %s",
                _APPLE_ROOT_CA_G3_PATH,
            )
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment="unknown",
                raw_status=-5,
                error="apple_root_ca_missing",
            )

        environment = (
            Environment.PRODUCTION if environment_name == "Production" else Environment.SANDBOX
        )
        root_cert_bytes = _APPLE_ROOT_CA_G3_PATH.read_bytes()

        try:
            verifier = SignedDataVerifier(
                root_certificates=[root_cert_bytes],
                # CRL/OCSP online checks add ~500ms per call and rely on
                # Apple's revocation list being reachable. For our scale
                # the signed-by-Apple guarantee is enough; revocation
                # checks are a TECH_DEBT item.
                enable_online_checks=False,
                bundle_id=BUNDLE_ID,
                app_apple_id=APP_APPLE_ID,
                environment=environment,
            )
            payload = verifier.verify_and_decode_signed_transaction(signed_transaction)
        except Exception as e:
            logger.warning(
                "[apple_iap] JWS verify failed env=%s: %s",
                environment_name,
                e,
            )
            return AppleVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=None,
                expires_at=None,
                original_transaction_id=None,
                environment=environment_name,
                raw_status=-6,
                error=f"jws_verify: {e.__class__.__name__}: {e}",
            )

        # JWSTransactionDecodedPayload fields: productId, transactionId,
        # originalTransactionId, expiresDate (ms epoch), purchaseDate, etc.
        expires_at = None
        if payload.expiresDate:
            expires_at = datetime.fromtimestamp(payload.expiresDate / 1000.0, tz=timezone.utc)

        is_active = bool(expires_at and expires_at > datetime.now(timezone.utc))

        logger.info(
            "[apple_iap] JWS verified env=%s product=%s tx=%s orig_tx=%s expires=%s active=%s",
            environment_name,
            payload.productId,
            payload.transactionId,
            payload.originalTransactionId,
            expires_at,
            is_active,
        )

        return AppleVerifyResult(
            is_valid=True,
            is_active_subscription=is_active,
            product_id=payload.productId,
            expires_at=expires_at,
            original_transaction_id=payload.originalTransactionId,
            environment=environment_name,
            raw_status=0,
        )

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
