"""Google Play Developer API subscription verification.

When a user purchases via Google Play Billing, the Flutter plugin hands
back a `purchaseToken` string. We forward it here, call the Google Play
Developer API to confirm the subscription is active, and if so flip the
user's plan to PRO via the existing `SubscriptionService.activate_subscription`
path.

Authentication uses a GCP service account. Store the full service-account
JSON in the `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` environment variable.
The account needs the "View financial data" permission in Play Console
(Settings → Users & permissions → account-level permissions).

Google Play Developer API endpoint:
  GET /androidpublisher/v3/applications/{packageName}/
      purchases/subscriptions/{subscriptionId}/tokens/{token}

Relevant response fields
------------------------
  expiryTimeMillis — subscription end epoch-ms (required)
  paymentState     — 1=received, 2=free_trial (absent if expired)
  purchaseType     — 0=test purchase, 1=promo; absent = real money
  cancelReason     — present when subscription was cancelled
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
_BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"

# Package name must match the applicationId in android/app/build.gradle.
PACKAGE_NAME = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "kz.aima.aima")

SERVICE_ACCOUNT_JSON_ENV = "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"

# subscriptionsv2 states that mean the user is within a paid/entitled period.
# CANCELED = auto-renew off but access continues until expiry, so still entitled.
_V2_ACTIVE_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    "SUBSCRIPTION_STATE_CANCELED",
}


def _parse_rfc3339(value: str | None) -> datetime | None:
    """Parse a Google RFC3339 timestamp (e.g. '2026-07-09T12:00:00Z')."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class AndroidVerifyResult:
    """Normalised verifier output.

    Keeps Google's raw API shape out of the route handler — if the API
    version changes, only this verifier changes.
    """

    is_valid: bool  # credentials resolved + API returned 200
    is_active_subscription: bool  # payment confirmed + not yet expired
    product_id: str | None
    expires_at: datetime | None
    environment: str  # "Production" | "Sandbox" (test purchase)
    error: str | None = None
    # obfuscatedExternalAccountId echoed by Google when the client set
    # applicationUserName at purchase. Lets an RTDN recover the user even when
    # the initial /verify never recorded a Payment binding (offline/reinstall).
    obfuscated_account_id: str | None = None


def parse_subscriptionsv2(
    payload: dict, fallback_product_id: str
) -> AndroidVerifyResult:
    """Interpret a Google Play `purchases.subscriptionsv2` 200 response.

    Pure (apart from `now`) so it is unit-testable without calling Google.
    - environment: Sandbox when `testPurchase` is present.
    - is_active: entitled subscriptionState AND latest lineItem expiry in future.
    - expires_at / product_id: taken from lineItems.
    """
    environment = (
        "Sandbox" if payload.get("testPurchase") is not None else "Production"
    )
    state = payload.get("subscriptionState", "")

    expires_at: datetime | None = None
    product_from_payload: str | None = None
    for item in payload.get("lineItems", []):
        if item.get("productId"):
            product_from_payload = item["productId"]
        exp = _parse_rfc3339(item.get("expiryTime"))
        if exp and (expires_at is None or exp > expires_at):
            expires_at = exp

    is_active = bool(
        state in _V2_ACTIVE_STATES
        and expires_at
        and expires_at > datetime.now(UTC)
    )
    external = payload.get("externalAccountIdentifiers") or {}
    obfuscated_account_id = external.get("obfuscatedExternalAccountId") or None
    return AndroidVerifyResult(
        is_valid=True,
        is_active_subscription=is_active,
        product_id=product_from_payload or fallback_product_id,
        expires_at=expires_at,
        environment=environment,
        obfuscated_account_id=obfuscated_account_id,
    )


class AndroidIAPVerifier:
    """Pure-stateless verifier — instantiate once per process, call verify() many times."""

    def __init__(
        self,
        service_account_json: str | None = None,
        package_name: str = PACKAGE_NAME,
        timeout_seconds: float = 10.0,
    ) -> None:
        raw_json = service_account_json or os.getenv(SERVICE_ACCOUNT_JSON_ENV)
        self._credentials: service_account.Credentials | None = None
        self._package_name = package_name
        self._timeout = timeout_seconds

        if raw_json:
            try:
                info = json.loads(raw_json)
                self._credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=[_ANDROID_PUBLISHER_SCOPE],
                )
            except Exception as exc:
                logger.error(
                    "Failed to parse %s: %s — verify() will reject every token.",
                    SERVICE_ACCOUNT_JSON_ENV,
                    exc,
                )
        else:
            logger.warning(
                "%s not set — verify() will reject every purchase token. "
                "Configure before enabling Google Play Billing in production.",
                SERVICE_ACCOUNT_JSON_ENV,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, purchase_token: str, product_id: str) -> AndroidVerifyResult:
        """Validate a Google Play purchase token for the given subscription product.

        Returns an `AndroidVerifyResult` with `is_valid=True` only when
        the Play API returned 200. `is_active_subscription=True` further
        narrows to "payment confirmed and subscription period has not
        expired yet".
        """
        if not self._credentials:
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error=f"{SERVICE_ACCOUNT_JSON_ENV} not configured or invalid",
            )

        try:
            token = self._get_access_token()
        except Exception as exc:
            logger.exception("Google service-account token refresh failed: %s", exc)
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error=f"auth: {exc.__class__.__name__}",
            )

        # subscriptionsv2 is the model-correct endpoint for base-plan/offer
        # subscriptions (the deprecated v1 `subscriptions.get` can misreport
        # status/expiry for them). v2 keys off the token only — no product_id in
        # the path.
        url = (
            f"{_BASE_URL}/applications/{self._package_name}"
            f"/purchases/subscriptionsv2/tokens/{purchase_token}"
        )
        return self._call_api(url, token, product_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str:
        """Refresh credentials if expired and return a Bearer token."""
        assert self._credentials is not None
        if not self._credentials.valid:
            self._credentials.refresh(GoogleRequest())
        return self._credentials.token  # type: ignore[return-value]

    def _call_api(self, url: str, access_token: str, product_id: str) -> AndroidVerifyResult:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.exception("Google Play API network error: %s", exc)
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error=f"network: {exc.__class__.__name__}",
            )

        if response.status_code == 404:
            # Token not found — purchase was cancelled, refunded, or the
            # token string is wrong. Not a server error; surface clearly.
            logger.warning("Google Play: token not found (404) for product %s", product_id)
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error="token not found",
            )

        if response.status_code == 410:
            # Token has been expired/voided by Google (e.g. charge-back).
            logger.warning("Google Play: token voided (410) for product %s", product_id)
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error="token voided",
            )

        if response.status_code != 200:
            logger.error(
                "Google Play API HTTP %s: %s",
                response.status_code,
                response.text[:300],
            )
            return AndroidVerifyResult(
                is_valid=False,
                is_active_subscription=False,
                product_id=product_id,
                expires_at=None,
                environment="unknown",
                error=f"http {response.status_code}",
            )

        result = parse_subscriptionsv2(response.json(), product_id)
        logger.info(
            "Google Play verify v2: product=%s expires=%s active=%s env=%s",
            result.product_id,
            result.expires_at,
            result.is_active_subscription,
            result.environment,
        )
        return result
