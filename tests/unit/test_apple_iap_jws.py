"""JWS detection + payload peek for Apple IAP receipts.

Covers the lightweight helpers that route between legacy base64 and
StoreKit 2 JWS without actually calling Apple or running the full
signature-verification path:

- _looks_like_jws — three-segment shape check.
- _peek_jws_payload — base64url decode of the middle segment.
- _env_from_claim / _other_env — environment claim normalisation.
- AppleIAPVerifier.verify — routes JWS-shaped receipts into the JWS
  branch and legacy receipts into the verifyReceipt branch.

The full signature-verification path (which calls into the
`app-store-server-library` C-extension chain) is not unit-tested here
because it would need a real Apple-signed payload. That's covered
end-to-end against the live deployment in the manual smoke test.
"""

import base64
import json
from unittest.mock import patch

import pytest

from payments.apple_iap import (
    AppleIAPVerifier,
    _env_from_claim,
    _looks_like_jws,
    _other_env,
    _peek_jws_payload,
)


# ─────────────────────────── _looks_like_jws ───────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("header.payload.signature", True),
        ("eyJhbGciOiJFUzI1NiJ9.eyJlbnYiOiJTYW5kYm94In0.AAAA", True),
        ("just-a-base64-blob-no-dots", False),
        ("MIIEFAYJKoZIhvcNAQcCoIIEBTCCBAECAQExDzANBglghkgBZQMEAgEFADCCAtgGCSqGSIb3DQEHAQ", False),
        ("", False),
        ("one.dot", False),  # only one dot
        ("three.dots.here.now", False),  # four segments, not JWS
    ],
)
def test_looks_like_jws(raw, expected):
    assert _looks_like_jws(raw) is expected


def test_looks_like_jws_none_safe():
    assert _looks_like_jws(None) is False


# ─────────────────────────── _peek_jws_payload ───────────────────────────


def _make_jws(payload_dict: dict) -> str:
    """Build a syntactically-valid JWS (without a real signature) so we
    can exercise _peek_jws_payload without standing up Apple's lib."""
    header = base64.urlsafe_b64encode(b'{"alg":"ES256","x5c":[]}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode()).rstrip(b"=").decode()
    sig = "AAAA"
    return f"{header}.{payload}.{sig}"


def test_peek_jws_payload_decodes_environment_claim():
    jws = _make_jws({"environment": "Sandbox", "productId": "kz.aima.aima.pro.monthly"})

    result = _peek_jws_payload(jws)

    assert result["environment"] == "Sandbox"
    assert result["productId"] == "kz.aima.aima.pro.monthly"


def test_peek_jws_payload_handles_stripped_base64_padding():
    """base64url often strips trailing `=`. The peek helper has to
    re-pad before decode or json.loads sees garbage."""
    # Force the payload length to be one short of a multiple of 4 so
    # padding is required.
    jws = _make_jws({"k": "v"})

    # Should not raise
    result = _peek_jws_payload(jws)
    assert result == {"k": "v"}


def test_peek_jws_payload_returns_dict_for_storekit2_shape():
    """Sanity: a payload with the typical StoreKit 2 keys round-trips."""
    payload = {
        "productId": "kz.aima.aima.pro.monthly",
        "transactionId": "2000000123456",
        "originalTransactionId": "2000000098765",
        "expiresDate": 1778952975000,
        "environment": "Sandbox",
        "bundleId": "kz.aima.aima",
    }
    jws = _make_jws(payload)

    result = _peek_jws_payload(jws)

    assert result == payload


# ─────────────────────────── _env_from_claim / _other_env ───────────────────────────


def test_env_from_claim_production_maps_to_production():
    assert _env_from_claim("Production") == "Production"


def test_env_from_claim_sandbox_maps_to_sandbox():
    assert _env_from_claim("Sandbox") == "Sandbox"


def test_env_from_claim_none_defaults_to_sandbox():
    """TestFlight is Sandbox; defaulting Production when we have no
    signal would silently misroute TestFlight verifications."""
    assert _env_from_claim(None) == "Sandbox"


def test_env_from_claim_xcode_treated_as_sandbox():
    """StoreKit local testing modes (Xcode, LocalTesting) aren't valid
    Apple environments for verification — treat them as Sandbox so the
    verifier at least attempts something sensible."""
    assert _env_from_claim("Xcode") == "Sandbox"
    assert _env_from_claim("LocalTesting") == "Sandbox"


def test_other_env_inverts():
    assert _other_env("Production") == "Sandbox"
    assert _other_env("Sandbox") == "Production"


# ─────────────────────────── verify() routing ───────────────────────────


def _verifier_with_secret() -> AppleIAPVerifier:
    """An AppleIAPVerifier whose shared secret is set, so we get past
    the early return that would otherwise mask routing behaviour."""
    return AppleIAPVerifier(shared_secret="test-secret")


def test_verify_routes_jws_shape_into_jws_branch():
    """Three-segment input must hit _verify_jws, not _call_endpoint
    (which would talk to /verifyReceipt and get a 21002)."""
    v = _verifier_with_secret()
    jws = _make_jws({"environment": "Sandbox"})

    with patch.object(v, "_verify_jws") as jws_branch, patch.object(v, "_call_endpoint") as legacy_branch:
        jws_branch.return_value = "jws-result-sentinel"
        v.verify(jws)

    jws_branch.assert_called_once_with(jws)
    legacy_branch.assert_not_called()


def test_verify_routes_legacy_base64_into_call_endpoint():
    """No dots → assumed base64 receipt → /verifyReceipt path."""
    v = _verifier_with_secret()
    legacy_receipt = "MIIEFAYJKoZIhvcNAQcCoIIEBTCCBAECAQExDzAN" * 100

    with patch.object(v, "_verify_jws") as jws_branch, patch.object(v, "_call_endpoint") as legacy_branch:
        from payments.apple_iap import AppleVerifyResult

        # Production endpoint returns a non-21007 status, so we exit
        # the verify() without the sandbox retry.
        legacy_branch.return_value = AppleVerifyResult(
            is_valid=True,
            is_active_subscription=True,
            product_id="kz.aima.aima.pro.monthly",
            expires_at=None,
            original_transaction_id="123",
            environment="Production",
            raw_status=0,
        )
        v.verify(legacy_receipt)

    jws_branch.assert_not_called()
    legacy_branch.assert_called()


def test_verify_returns_early_if_shared_secret_missing(monkeypatch):
    """Belt-and-suspenders: if APPLE_APP_SHARED_SECRET wasn't passed
    AND wasn't in env, every receipt rejects immediately — neither
    branch is touched."""
    monkeypatch.delenv("APPLE_APP_SHARED_SECRET", raising=False)
    v = AppleIAPVerifier()  # no explicit secret → reads env (now missing)

    with patch.object(v, "_verify_jws") as jws_branch, patch.object(v, "_call_endpoint") as legacy_branch:
        result = v.verify("anything.could.go.here")

    assert result.is_valid is False
    assert "APPLE_APP_SHARED_SECRET" in (result.error or "")
    jws_branch.assert_not_called()
    legacy_branch.assert_not_called()


def test_verify_handles_empty_string_without_routing():
    """Empty receipt isn't JWS-shaped and shouldn't even try the legacy
    endpoint — though current impl still calls verifyReceipt with an
    empty receipt-data and lets Apple return 21002. This test pins the
    behaviour so a future refactor that adds an explicit empty-string
    short-circuit is intentional, not accidental."""
    v = _verifier_with_secret()

    with patch.object(v, "_call_endpoint") as legacy_branch:
        from payments.apple_iap import AppleVerifyResult

        legacy_branch.return_value = AppleVerifyResult(
            is_valid=False,
            is_active_subscription=False,
            product_id=None,
            expires_at=None,
            original_transaction_id=None,
            environment="Production",
            raw_status=21002,
        )
        v.verify("")

    legacy_branch.assert_called_once()


# ─────────────────────────── _verify_jws environment fallback ───────────────────────────


def test_verify_jws_tries_other_env_on_first_env_failure():
    """If the JWS payload claims Production but Apple's verifier fails
    against Production, we retry with Sandbox before giving up. This is
    the same idea as the 21007 retry in the legacy path."""
    v = _verifier_with_secret()
    jws = _make_jws({"environment": "Production"})

    from payments.apple_iap import AppleVerifyResult

    fail = AppleVerifyResult(
        is_valid=False,
        is_active_subscription=False,
        product_id=None,
        expires_at=None,
        original_transaction_id=None,
        environment="Production",
        raw_status=-6,
        error="jws_verify: sig fail",
    )
    success = AppleVerifyResult(
        is_valid=True,
        is_active_subscription=True,
        product_id="kz.aima.aima.pro.monthly",
        expires_at=None,
        original_transaction_id="x",
        environment="Sandbox",
        raw_status=0,
    )

    with patch.object(v, "_verify_jws_one_env", side_effect=[fail, success]) as one_env:
        result = v._verify_jws(jws)

    assert result.is_valid is True
    assert one_env.call_count == 2
    calls_envs = [c.args[1] for c in one_env.call_args_list]
    assert calls_envs == ["Production", "Sandbox"]


def test_verify_jws_does_not_retry_when_primary_env_succeeds():
    v = _verifier_with_secret()
    jws = _make_jws({"environment": "Sandbox"})

    from payments.apple_iap import AppleVerifyResult

    success = AppleVerifyResult(
        is_valid=True,
        is_active_subscription=True,
        product_id="kz.aima.aima.pro.monthly",
        expires_at=None,
        original_transaction_id="x",
        environment="Sandbox",
        raw_status=0,
    )

    with patch.object(v, "_verify_jws_one_env", return_value=success) as one_env:
        result = v._verify_jws(jws)

    assert result.is_valid is True
    one_env.assert_called_once()


def test_verify_jws_returns_failure_when_both_envs_fail():
    v = _verifier_with_secret()
    jws = _make_jws({"environment": "Sandbox"})

    from payments.apple_iap import AppleVerifyResult

    fail = AppleVerifyResult(
        is_valid=False,
        is_active_subscription=False,
        product_id=None,
        expires_at=None,
        original_transaction_id=None,
        environment="Sandbox",
        raw_status=-6,
        error="jws_verify: sig fail",
    )

    with patch.object(v, "_verify_jws_one_env", return_value=fail):
        result = v._verify_jws(jws)

    assert result.is_valid is False
    assert result.raw_status == -6
