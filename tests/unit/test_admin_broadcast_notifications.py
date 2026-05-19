"""AdminBroadcastNotificationService — target filtering + the safety
gates around it.

The service is the engine behind POST /admin/notifications/send (the
endpoint the admin panel's Push-уведомления page calls). Most of the
risk is in the target filter: a bug there sends a marketing push to
the wrong slice — at best embarrassing, at worst Apple suspends the
Firebase project for abuse. These tests pin each filter path.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# Eager imports so SQLAlchemy mappers can resolve relationships
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from clients.firebase import FirebaseSendResult
from quiz.services.admin_broadcast_notifications import (
    AdminBroadcastNotificationService,
    BroadcastResult,
)


# ─────────────────────── test doubles ───────────────────────


class _FakeToken:
    """Drop-in for DailyTestDeviceToken. Only carries the fields the
    service reads (token / platform / student_guid / id)."""

    def __init__(
        self,
        id: int,
        token: str,
        platform: str | None,
        student_guid,
    ):
        self.id = id
        self.token = token
        self.platform = platform
        self.student_guid = student_guid


class _FakeRepo:
    """Stub DailyTestRepository. Returns the whole list on the first
    page and an empty list afterwards — the service iterates until
    fetch_device_tokens returns []."""

    def __init__(self, tokens: list[_FakeToken]):
        self._tokens = tokens
        self.deleted_tokens: list[str] = []

    def fetch_device_tokens(self, *, last_id=None, limit=1000):
        if last_id is not None:
            return []
        return list(self._tokens)

    def delete_tokens(self, tokens: list[str]) -> int:
        self.deleted_tokens.extend(tokens)
        return len(tokens)


def _build_service(
    *,
    tokens: list[_FakeToken],
    firebase_enabled: bool = True,
    keycloak_users=None,
    keycloak_raises: bool = False,
):
    """Wire up the service against fakes. `keycloak_users` is a list
    of (user_id, plan) tuples; the IdP fake builds DTO-shaped objects
    so the service's `getattr(u, 'attributes')` etc. work unchanged."""

    firebase_client = MagicMock()
    firebase_client.enabled = firebase_enabled
    firebase_client.broadcast.return_value = FirebaseSendResult(
        requested=len(tokens), success=len(tokens), failure=0, invalid_tokens=[]
    )

    firebase_settings = MagicMock()
    firebase_settings.fetch_chunk_size = 1000

    database = MagicMock()
    database.session = MagicMock()

    idp = MagicMock()

    def _make_user(user_id, plan):
        u = MagicMock()
        u.id = user_id
        u.attributes = MagicMock()
        u.attributes.plan = [plan] if plan else None
        return u

    if keycloak_raises:
        idp.get_users.side_effect = RuntimeError("keycloak unreachable")
    else:
        idp.get_users.return_value = [
            _make_user(uid, plan) for uid, plan in (keycloak_users or [])
        ]

    service = AdminBroadcastNotificationService(
        database=database,
        firebase_client=firebase_client,
        firebase_settings=firebase_settings,
        identity_provider=idp,
    )

    # Patch the repo constructor the service uses internally
    import quiz.services.admin_broadcast_notifications as svc_module

    svc_module.DailyTestRepository = lambda session: _FakeRepo(tokens)

    return service, firebase_client, idp


# ─────────────────────── disabled-Firebase guard ───────────────────────


def test_returns_empty_when_firebase_disabled():
    """If Firebase isn't configured the service must not pretend to
    have sent anything — and crucially, must not crash the request.
    The admin endpoint converts this empty result into a 503 above."""
    service, firebase_client, _ = _build_service(
        tokens=[], firebase_enabled=False
    )

    result = service.send(title="t", body="b", target="all")

    assert result == BroadcastResult(
        target="all",
        matched_tokens=0,
        requested=0,
        delivered=0,
        failed=0,
        removed_tokens=0,
    )
    firebase_client.broadcast.assert_not_called()


# ─────────────────────── target=all ───────────────────────


def test_target_all_sends_to_every_token():
    user_a, user_b = str(uuid4()), str(uuid4())
    tokens = [
        _FakeToken(1, "tok_ios", "ios", user_a),
        _FakeToken(2, "tok_android", "android", user_b),
    ]
    service, firebase_client, _ = _build_service(tokens=tokens)

    result = service.send(title="t", body="b", target="all")

    assert result.matched_tokens == 2
    firebase_client.broadcast.assert_called_once()
    sent_tokens = firebase_client.broadcast.call_args.args[0]
    assert set(sent_tokens) == {"tok_ios", "tok_android"}


# ─────────────────────── target=ios ───────────────────────


def test_target_ios_filters_to_ios_platform():
    """Operator wants to push only to iOS users (e.g. a new App Store
    build is live). Service must drop android/web/null platforms."""
    user = str(uuid4())
    tokens = [
        _FakeToken(1, "ios_a", "ios", user),
        _FakeToken(2, "ios_b", "iOS", user),  # case-insensitive
        _FakeToken(3, "android_a", "android", user),
        _FakeToken(4, "null_platform", None, user),
    ]
    service, firebase_client, _ = _build_service(tokens=tokens)

    result = service.send(title="t", body="b", target="ios")

    assert result.matched_tokens == 2
    sent_tokens = firebase_client.broadcast.call_args.args[0]
    assert set(sent_tokens) == {"ios_a", "ios_b"}


def test_target_ios_with_no_ios_users_skips_send():
    """No iOS tokens → matched=0 and FCM not called at all (avoids
    sending an empty payload that would still spend an API call)."""
    user = str(uuid4())
    tokens = [
        _FakeToken(1, "android", "android", user),
    ]
    service, firebase_client, _ = _build_service(tokens=tokens)

    result = service.send(title="t", body="b", target="ios")

    assert result.matched_tokens == 0
    assert result.requested == 0
    firebase_client.broadcast.assert_not_called()


# ─────────────────────── target=pro ───────────────────────


def test_target_pro_filters_to_pro_users_only():
    """Operator wants to push only to PRO subscribers (e.g. an
    exclusive feature announcement). Service must hit Keycloak once,
    build the PRO user-id set, and drop FREE-plan tokens."""
    pro_user = str(uuid4())
    free_user = str(uuid4())
    tokens = [
        _FakeToken(1, "pro_ios", "ios", pro_user),
        _FakeToken(2, "pro_android", "android", pro_user),
        _FakeToken(3, "free_ios", "ios", free_user),
    ]
    service, firebase_client, idp = _build_service(
        tokens=tokens,
        keycloak_users=[(pro_user, "PRO"), (free_user, "FREE")],
    )

    result = service.send(title="t", body="b", target="pro")

    assert result.matched_tokens == 2
    idp.get_users.assert_called_once()
    sent_tokens = firebase_client.broadcast.call_args.args[0]
    assert set(sent_tokens) == {"pro_ios", "pro_android"}


def test_target_pro_case_insensitive_plan_match():
    """Keycloak stores plan as the string from PlanType (`PRO`), but
    a defensive equality check should also handle stray `pro` /
    `Pro` so a future refactor of the attribute writer doesn't
    silently empty the PRO audience."""
    pro_user = str(uuid4())
    tokens = [_FakeToken(1, "tok", "ios", pro_user)]
    service, _, _ = _build_service(
        tokens=tokens,
        keycloak_users=[(pro_user, "pro")],
    )

    result = service.send(title="t", body="b", target="pro")
    assert result.matched_tokens == 1


def test_target_pro_returns_empty_when_no_pro_users_exist():
    """All users are FREE → Keycloak returns no PRO ids → matched=0,
    FCM never called, result reports zero deliveries cleanly."""
    free_user = str(uuid4())
    tokens = [_FakeToken(1, "tok", "ios", free_user)]
    service, firebase_client, _ = _build_service(
        tokens=tokens,
        keycloak_users=[(free_user, "FREE")],
    )

    result = service.send(title="t", body="b", target="pro")

    assert result.matched_tokens == 0
    assert result.requested == 0
    firebase_client.broadcast.assert_not_called()


def test_target_pro_keycloak_failure_returns_empty_safely():
    """If the Keycloak admin call itself raises (e.g. realm offline),
    the service must NOT fall back to sending to everyone — that
    would silently broaden the audience. Return zero deliveries
    and log the error; the admin can retry."""
    user = str(uuid4())
    tokens = [_FakeToken(1, "tok", "ios", user)]
    service, firebase_client, _ = _build_service(
        tokens=tokens,
        keycloak_raises=True,
    )

    result = service.send(title="t", body="b", target="pro")

    assert result.matched_tokens == 0
    assert result.requested == 0
    firebase_client.broadcast.assert_not_called()


# ─────────────────────── invalid-token cleanup ───────────────────────


def test_invalid_tokens_returned_by_firebase_are_pruned():
    """When FCM reports UNREGISTERED for a token, the service must
    delete it from the daily_test_device_tokens table so the next
    broadcast doesn't try the same dead token. `removed_tokens` in
    the result reflects how many were cleaned up."""
    user = str(uuid4())
    tokens = [
        _FakeToken(1, "alive", "ios", user),
        _FakeToken(2, "dead", "ios", user),
    ]
    service, firebase_client, _ = _build_service(tokens=tokens)
    # Override the stub broadcast: 1 success, 1 invalid
    firebase_client.broadcast.return_value = FirebaseSendResult(
        requested=2, success=1, failure=1, invalid_tokens=["dead"]
    )

    result = service.send(title="t", body="b", target="all")

    assert result.matched_tokens == 2
    assert result.delivered == 1
    assert result.failed == 1
    assert result.removed_tokens == 1


# ─────────────────────── data payload ───────────────────────


def test_data_payload_includes_target_for_client_routing():
    """The default `data` we attach to a broadcast tags it with the
    target slice so the Flutter app can route taps (e.g. PRO push →
    open subscription screen) without an extra round-trip. This
    contract is observable from FCM, so test it explicitly."""
    user = str(uuid4())
    tokens = [_FakeToken(1, "tok", "ios", user)]
    service, firebase_client, _ = _build_service(tokens=tokens)

    service.send(title="t", body="b", target="ios")

    data_kwarg = firebase_client.broadcast.call_args.kwargs.get("data")
    assert data_kwarg == {"type": "admin_broadcast", "target": "ios"}


def test_custom_data_overrides_default_payload():
    user = str(uuid4())
    tokens = [_FakeToken(1, "tok", "ios", user)]
    service, firebase_client, _ = _build_service(tokens=tokens)

    service.send(title="t", body="b", target="all", data={"type": "promo", "code": "X"})

    data_kwarg = firebase_client.broadcast.call_args.kwargs.get("data")
    assert data_kwarg == {"type": "promo", "code": "X"}
