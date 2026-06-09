"""Security coverage for the payment endpoints — calling the async handlers
directly with fakes (no live backend, no real Google tokens).

Threats covered:
- product spoofing      → /verify rejects unknown product_id (#5)
- token replay/theft    → /verify rejects a token bound to another account (#1)
- forged "active"       → invalid / inactive Google tokens never grant PRO
- expiry source-of-truth→ Google's expiry is what gets written (#9)
- refund keeps PRO      → voided / REVOKED RTDN strips PRO (#3)
- RTDN auth bypass      → wrong/missing secret rejected; header path works (#14)
- CANCELED ≠ revoke     → soft cancel keeps access until period end
"""

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

# SQLAlchemy mapper resolution (Payment/Subscription relationships)
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from api.routes.payments import android
from api.routes.payments.android import (
    AndroidVerifyIn,
    google_rtdn,
    verify_android_purchase,
)
from auth.dtos.users import UserDTO
from common.enums import PlanType
from payments.android_iap import AndroidVerifyResult

PRO = "kz.aima.aima.pro.monthly"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _user() -> UserDTO:
    return UserDTO(
        id=uuid4(),
        username="u",
        name="U",
        email="u@example.com",
        phone="+77001234567",
        plan=PlanType.FREE,
        subscription_end=None,
        used_trial=False,
        is_active=True,
    )


class _Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self._result


class _Session:
    """Returns a configurable existing Payment for both the token-owner lookup
    and the dedup check; records add/commit so nothing explodes."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.committed = False

    def query(self, *_a, **_k):
        return _Query(self.existing)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


class _SubService:
    def __init__(self):
        self.activated = []
        self.revoked = []

    async def activate_subscription(self, user, plan, months=1, expires_at=None):
        self.activated.append(
            {"user": user, "plan": plan, "months": months, "expires_at": expires_at}
        )
        return user.model_copy(update={"plan": plan, "subscription_end": expires_at})

    def revoke_subscription(self, user):
        self.revoked.append(user)
        return user.model_copy(update={"plan": PlanType.FREE, "subscription_end": None})


class _Users:
    def __init__(self, user):
        self._user = user

    def get(self, _query):
        return self._user


class _Verifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify(self, token, product_id):
        self.calls.append((token, product_id))
        return self.result


class _Req:
    def __init__(self, notif: dict | None):
        self._notif = notif

    async def json(self):
        if self._notif is None:
            return {}
        data = base64.b64encode(json.dumps(self._notif).encode()).decode()
        return {"message": {"data": data}}


def _result(*, is_valid=True, is_active=True, expires_at=None, env="Production"):
    return AndroidVerifyResult(
        is_valid=is_valid,
        is_active_subscription=is_active,
        product_id=PRO,
        expires_at=expires_at,
        environment=env,
    )


# --------------------------------------------------------------------------- #
# /verify — product validation, replay, forged-active (#1, #5, #9)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_verify_rejects_unknown_product(monkeypatch):
    monkeypatch.setattr(android, "_verifier", _Verifier(_result()))
    with pytest.raises(HTTPException) as exc:
        await verify_android_purchase(
            AndroidVerifyIn(purchase_token="t", product_id="com.evil.cheap"),
            current_user=_user(),
            subscription_service=_SubService(),
            db_session=_Session(),
            plan_service=MagicMock(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(android, "_verifier", _Verifier(_result(is_valid=False)))
    with pytest.raises(HTTPException) as exc:
        await verify_android_purchase(
            AndroidVerifyIn(purchase_token="bad", product_id=PRO),
            current_user=_user(),
            subscription_service=_SubService(),
            db_session=_Session(),
            plan_service=MagicMock(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_rejects_token_owned_by_another_account(monkeypatch):
    monkeypatch.setattr(android, "_verifier", _Verifier(_result()))
    other_owner = SimpleNamespace(user_id=str(uuid4()))  # different user
    sub = _SubService()
    with pytest.raises(HTTPException) as exc:
        await verify_android_purchase(
            AndroidVerifyIn(purchase_token="shared", product_id=PRO),
            current_user=_user(),
            subscription_service=sub,
            db_session=_Session(existing=other_owner),
            plan_service=MagicMock(),
        )
    assert exc.value.status_code == 409
    assert sub.activated == []  # PRO never granted on replay


@pytest.mark.asyncio
async def test_verify_inactive_subscription_does_not_grant_pro(monkeypatch):
    monkeypatch.setattr(android, "_verifier", _Verifier(_result(is_active=False)))
    sub = _SubService()
    out = await verify_android_purchase(
        AndroidVerifyIn(purchase_token="t", product_id=PRO),
        current_user=_user(),
        subscription_service=sub,
        db_session=_Session(),
        plan_service=MagicMock(),
    )
    assert out.is_active is False
    assert sub.activated == []


@pytest.mark.asyncio
async def test_verify_active_grants_pro_with_google_expiry(monkeypatch):
    from datetime import datetime, timedelta, timezone

    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    monkeypatch.setattr(android, "_verifier", _Verifier(_result(expires_at=expiry)))
    sub = _SubService()
    out = await verify_android_purchase(
        AndroidVerifyIn(purchase_token="fresh", product_id=PRO),
        current_user=_user(),
        subscription_service=sub,
        db_session=_Session(existing=None),
        plan_service=MagicMock(),
    )
    assert out.is_active is True
    assert len(sub.activated) == 1
    # #9 — Google's expiry is the source of truth, not a hardcoded 30 days.
    assert sub.activated[0]["expires_at"] == expiry


@pytest.mark.asyncio
async def test_verify_same_owner_reverify_is_allowed(monkeypatch):
    monkeypatch.setattr(android, "_verifier", _Verifier(_result()))
    user = _user()
    same_owner = SimpleNamespace(user_id=str(user.id))
    sub = _SubService()
    out = await verify_android_purchase(
        AndroidVerifyIn(purchase_token="t", product_id=PRO),
        current_user=user,
        subscription_service=sub,
        db_session=_Session(existing=same_owner),
        plan_service=MagicMock(),
    )
    assert out.is_active is True
    assert len(sub.activated) == 1  # idempotent re-verify by the owner is fine


# --------------------------------------------------------------------------- #
# /rtdn — auth bypass + entitlement sync (#3, #14)
# --------------------------------------------------------------------------- #


async def _call_rtdn(monkeypatch, *, notif, token="", header="", db=None, sub=None):
    monkeypatch.setenv("GOOGLE_RTDN_SECRET", "s3cret")
    monkeypatch.setattr(android, "_verifier", _Verifier(_result()))
    return await google_rtdn(
        _Req(notif),
        token=token,
        x_rtdn_secret=header,
        db_session=db or _Session(),
        plan_service=MagicMock(),
        subscription_service=sub or _SubService(),
        users=_Users(_user()),
    )


@pytest.mark.asyncio
async def test_rtdn_rejects_wrong_secret(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await _call_rtdn(monkeypatch, notif=None, token="wrong")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rtdn_rejects_missing_secret_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_RTDN_SECRET", raising=False)
    monkeypatch.setattr(android, "_verifier", _Verifier(_result()))
    with pytest.raises(HTTPException) as exc:
        await google_rtdn(
            _Req(None),
            token="anything",
            x_rtdn_secret="anything",
            db_session=_Session(),
            plan_service=MagicMock(),
            subscription_service=_SubService(),
            users=_Users(_user()),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rtdn_accepts_secret_via_header(monkeypatch):
    out = await _call_rtdn(monkeypatch, notif=None, header="s3cret")
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_rtdn_refund_revokes_pro(monkeypatch):
    owner = SimpleNamespace(user_id=str(uuid4()))
    sub = _SubService()
    notif = {"voidedPurchaseNotification": {"purchaseToken": "T", "orderId": "O"}}
    await _call_rtdn(
        monkeypatch, notif=notif, header="s3cret", db=_Session(existing=owner), sub=sub
    )
    assert len(sub.revoked) == 1  # refund stripped PRO


@pytest.mark.asyncio
async def test_rtdn_revoked_event_revokes_pro(monkeypatch):
    owner = SimpleNamespace(user_id=str(uuid4()))
    sub = _SubService()
    notif = {
        "subscriptionNotification": {
            "notificationType": 12,  # REVOKED
            "purchaseToken": "T",
            "subscriptionId": PRO,
        }
    }
    await _call_rtdn(
        monkeypatch, notif=notif, header="s3cret", db=_Session(existing=owner), sub=sub
    )
    assert len(sub.revoked) == 1
    assert sub.activated == []


@pytest.mark.asyncio
async def test_rtdn_canceled_event_does_not_revoke(monkeypatch):
    owner = SimpleNamespace(user_id=str(uuid4()))
    sub = _SubService()
    notif = {
        "subscriptionNotification": {
            "notificationType": 3,  # CANCELED — keep access until period end
            "purchaseToken": "T",
            "subscriptionId": PRO,
        }
    }
    await _call_rtdn(
        monkeypatch, notif=notif, header="s3cret", db=_Session(existing=owner), sub=sub
    )
    assert sub.revoked == []


@pytest.mark.asyncio
async def test_rtdn_renewal_extends_pro(monkeypatch):
    owner = SimpleNamespace(user_id=str(uuid4()))
    sub = _SubService()
    notif = {
        "subscriptionNotification": {
            "notificationType": 2,  # RENEWED
            "purchaseToken": "T",
            "subscriptionId": PRO,
        }
    }
    await _call_rtdn(
        monkeypatch, notif=notif, header="s3cret", db=_Session(existing=owner), sub=sub
    )
    assert len(sub.activated) == 1  # PRO extended on renewal


# --------------------------------------------------------------------------- #
# FreedomPay webhook — never ack a foreign order as success (#15)
# --------------------------------------------------------------------------- #


def test_freedompay_rejected_response_is_not_success():
    from api.routes.payments.webhook import (
        _create_rejected_response,
        _create_success_response,
    )

    data = {"pg_salt": "abc"}
    rejected = _create_rejected_response(data, "result_notify", "secret", "unknown order")
    success = _create_success_response(data, "result_notify", "secret")

    assert rejected.status_code == 200
    body = rejected.body.decode()
    assert "rejected" in body
    assert "<pg_status>ok</pg_status>" not in body  # must NOT ack as success
    # sanity: the success helper really does say ok, so the assertion is meaningful
    assert "<pg_status>ok</pg_status>" in success.body.decode()
