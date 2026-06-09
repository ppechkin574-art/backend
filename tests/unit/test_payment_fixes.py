"""Unit coverage for the payment hardening batch (review fixes #1, #5, #10, #13).

All pure / near-pure logic — no live Google/FreedomPay calls:

- #13 parse_subscriptionsv2 + _parse_rfc3339 — Google subscriptionsv2 response
  interpretation (the migration most in need of a safety net).
- #1  _token_order_id — stable token→order_id derivation (binds a purchase to
  one account; verify and RTDN must agree on it).
- #5  _ALLOWED_PRODUCT_IDS — only our PRO SKU may unlock PRO.
- #10 _amount_ok — FreedomPay "paid" must not activate PRO on underpayment.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from api.routes.payments.android import _ALLOWED_PRODUCT_IDS, _token_order_id
from api.routes.payments.webhook import _amount_ok
from payments.android_iap import _parse_rfc3339, parse_subscriptionsv2

PRO = "kz.aima.aima.pro.monthly"


def _future_iso(days: int = 30) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------- #
# #13 — subscriptionsv2 parsing
# --------------------------------------------------------------------------- #


def test_v2_active_with_future_expiry_is_active():
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "lineItems": [{"productId": PRO, "expiryTime": _future_iso()}],
    }
    res = parse_subscriptionsv2(payload, "fallback")
    assert res.is_valid is True
    assert res.is_active_subscription is True
    assert res.product_id == PRO
    assert res.expires_at is not None
    assert res.environment == "Production"


def test_v2_canceled_but_not_yet_expired_still_active():
    # Auto-renew off but access continues until expiry → still entitled.
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_CANCELED",
        "lineItems": [{"productId": PRO, "expiryTime": _future_iso()}],
    }
    assert parse_subscriptionsv2(payload, PRO).is_active_subscription is True


def test_v2_expired_state_is_not_active():
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_EXPIRED",
        "lineItems": [{"productId": PRO, "expiryTime": _past_iso()}],
    }
    assert parse_subscriptionsv2(payload, PRO).is_active_subscription is False


def test_v2_active_state_but_past_expiry_is_not_active():
    # Expiry in the past overrides an "active" state.
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "lineItems": [{"productId": PRO, "expiryTime": _past_iso()}],
    }
    assert parse_subscriptionsv2(payload, PRO).is_active_subscription is False


def test_v2_test_purchase_is_sandbox():
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "testPurchase": {},
        "lineItems": [{"productId": PRO, "expiryTime": _future_iso()}],
    }
    assert parse_subscriptionsv2(payload, PRO).environment == "Sandbox"


def test_v2_picks_latest_line_item_expiry():
    earlier = _future_iso(10)
    later = _future_iso(40)
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "lineItems": [
            {"productId": PRO, "expiryTime": earlier},
            {"productId": PRO, "expiryTime": later},
        ],
    }
    res = parse_subscriptionsv2(payload, PRO)
    assert res.expires_at == _parse_rfc3339(later)


def test_v2_no_line_items_falls_back_and_is_inactive():
    res = parse_subscriptionsv2({"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE"}, PRO)
    assert res.product_id == PRO
    assert res.expires_at is None
    assert res.is_active_subscription is False


# --------------------------------------------------------------------------- #
# #13 — RFC3339 parsing
# --------------------------------------------------------------------------- #


def test_parse_rfc3339_handles_z_suffix():
    dt = _parse_rfc3339("2026-07-09T12:00:00Z")
    assert dt is not None and dt.tzinfo is not None


def test_parse_rfc3339_handles_offset():
    assert _parse_rfc3339("2026-07-09T12:00:00+05:00") is not None


def test_parse_rfc3339_none_and_garbage():
    assert _parse_rfc3339(None) is None
    assert _parse_rfc3339("") is None
    assert _parse_rfc3339("not-a-date") is None


# --------------------------------------------------------------------------- #
# #1 — token→order_id derivation
# --------------------------------------------------------------------------- #


def test_token_order_id_is_deterministic_and_prefixed():
    a = _token_order_id("token-abc")
    b = _token_order_id("token-abc")
    assert a == b
    assert a.startswith("gplay-")
    assert len(a) == len("gplay-") + 40


def test_token_order_id_differs_per_token():
    assert _token_order_id("token-a") != _token_order_id("token-b")


# --------------------------------------------------------------------------- #
# #5 — product allow-list
# --------------------------------------------------------------------------- #


def test_pro_product_is_allowed_and_others_are_not():
    assert PRO in _ALLOWED_PRODUCT_IDS
    assert "com.some.other.product" not in _ALLOWED_PRODUCT_IDS


# --------------------------------------------------------------------------- #
# #10 — FreedomPay amount guard
# --------------------------------------------------------------------------- #


def _payment(amount):
    return SimpleNamespace(amount=amount)


def test_amount_ok_exact_match():
    assert _amount_ok({"pg_amount": "4990"}, _payment(Decimal("4990"))) is True


def test_amount_ok_overpayment_allowed():
    assert _amount_ok({"pg_amount": "5000"}, _payment(Decimal("4990"))) is True


def test_amount_ok_underpayment_rejected():
    assert _amount_ok({"pg_amount": "100"}, _payment(Decimal("4990"))) is False


def test_amount_ok_missing_field_is_permissive():
    assert _amount_ok({}, _payment(Decimal("4990"))) is True


def test_amount_ok_unparseable_is_permissive():
    assert _amount_ok({"pg_amount": "abc"}, _payment(Decimal("4990"))) is True


def test_amount_ok_no_order_amount_is_permissive():
    assert _amount_ok({"pg_amount": "4990"}, _payment(None)) is True
