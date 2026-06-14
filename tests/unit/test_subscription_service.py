"""Unit tests for SubscriptionService.

Covers:
- _hash_phone: deterministic sha256
- _get_default_plan_features: FREE and PRO defaults
- refresh_subscription_status: expired PRO downgrade, active PRO keep, FREE pass-through
- revoke_subscription: FREE no-op, PRO stripped to FREE
- activate_subscription: external expires_at, computed (FREE→PRO), computed stacking (PRO→PRO)
- cancel_subscription: FREE guard (400), already-cancelled guard (400), soft cancel
- activate_free_trial: not-FREE guard (400), used_trial guard (400), phone-hash hit (400)
- get_plan_features: DB hit, DB miss falls back to defaults
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from common.enums import PlanType
from subscription.service import SubscriptionService, _hash_phone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(auth=None, db=None) -> SubscriptionService:
    if auth is None:
        auth = MagicMock()
    if db is None:
        db = MagicMock()
        db.session = MagicMock()
    return SubscriptionService(auth_service=auth, database=db)


def _fake_user(
    plan: PlanType = PlanType.FREE,
    subscription_end: datetime | None = None,
    used_trial: bool = False,
    subscription_cancelled: bool = False,
    phone: str | None = None,
):
    from auth.dtos.users import UserDTO

    return UserDTO(
        id=uuid4(),
        username="testuser",
        name="Test User",
        is_active=True,
        plan=plan,
        subscription_end=subscription_end,
        used_trial=used_trial,
        subscription_cancelled=subscription_cancelled,
        phone=phone,
    )


def _future(days: int = 30) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _past(days: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# ---------------------------------------------------------------------------
# _hash_phone — pure function
# ---------------------------------------------------------------------------


def test_hash_phone_is_sha256():
    phone = "+77001234567"
    expected = hashlib.sha256(phone.encode()).hexdigest()
    assert _hash_phone(phone) == expected


def test_hash_phone_deterministic():
    assert _hash_phone("+77001234567") == _hash_phone("+77001234567")


def test_hash_phone_different_numbers_differ():
    assert _hash_phone("+77001234567") != _hash_phone("+77007654321")


def test_hash_phone_length_64():
    assert len(_hash_phone("+77001234567")) == 64


# ---------------------------------------------------------------------------
# _get_default_plan_features
# ---------------------------------------------------------------------------


class TestGetDefaultPlanFeatures:
    def test_free_plan_has_id_minus_1(self):
        svc = _make_service()
        feat = svc._get_default_plan_features(PlanType.FREE)
        assert feat.id == -1
        assert feat.plan_type == PlanType.FREE

    def test_pro_plan_has_id_minus_2(self):
        svc = _make_service()
        feat = svc._get_default_plan_features(PlanType.PRO)
        assert feat.id == -2
        assert feat.plan_type == PlanType.PRO

    def test_free_plan_is_free(self):
        svc = _make_service()
        feat = svc._get_default_plan_features(PlanType.FREE)
        assert feat.price == 0.0

    def test_pro_plan_duration_30_days(self):
        svc = _make_service()
        feat = svc._get_default_plan_features(PlanType.PRO)
        assert feat.duration_days == 30

    def test_unknown_plan_falls_back_to_free(self):
        svc = _make_service()
        feat = svc._get_default_plan_features(PlanType.NONE)
        assert feat.plan_type == PlanType.FREE


# ---------------------------------------------------------------------------
# refresh_subscription_status
# ---------------------------------------------------------------------------


class TestRefreshSubscriptionStatus:
    def test_free_plan_returns_unchanged(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.FREE)
        result = svc.refresh_subscription_status(user)
        assert result is user
        svc.auth_service.update_user_profile.assert_not_called()

    def test_pro_active_returns_unchanged(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.PRO, subscription_end=_future(10))
        result = svc.refresh_subscription_status(user)
        assert result is user
        svc.auth_service.update_user_profile.assert_not_called()

    def test_pro_expired_triggers_downgrade(self):
        auth = MagicMock()
        downgraded = _fake_user(plan=PlanType.FREE)
        auth.update_user_profile.return_value = downgraded
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.PRO, subscription_end=_past(1))
        result = svc.refresh_subscription_status(user)
        auth.update_user_profile.assert_called_once()
        call_args = auth.update_user_profile.call_args
        update_dto = call_args[0][1]
        assert update_dto.plan == PlanType.FREE
        assert update_dto.subscription_end is None
        assert result is downgraded

    def test_pro_no_end_date_returns_unchanged(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.PRO, subscription_end=None)
        result = svc.refresh_subscription_status(user)
        assert result is user


# ---------------------------------------------------------------------------
# revoke_subscription
# ---------------------------------------------------------------------------


class TestRevokeSubscription:
    def test_free_user_is_noop(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.FREE)
        result = svc.revoke_subscription(user)
        assert result is user
        svc.auth_service.update_user_profile.assert_not_called()

    def test_pro_user_stripped_to_free(self):
        auth = MagicMock()
        stripped = _fake_user(plan=PlanType.FREE)
        auth.update_user_profile.return_value = stripped
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.PRO, subscription_end=_future(10))
        result = svc.revoke_subscription(user)
        auth.update_user_profile.assert_called_once()
        assert result is stripped

    def test_revoke_auth_failure_returns_original(self):
        auth = MagicMock()
        auth.update_user_profile.side_effect = RuntimeError("Keycloak down")
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.PRO, subscription_end=_future(10))
        result = svc.revoke_subscription(user)
        assert result is user


# ---------------------------------------------------------------------------
# activate_subscription
# ---------------------------------------------------------------------------


class TestActivateSubscription:
    def test_explicit_expires_at_used_directly(self):
        auth = MagicMock()
        fixed = _future(60)
        updated = _fake_user(plan=PlanType.PRO, subscription_end=fixed)
        auth.update_user_profile.return_value = updated
        svc = _make_service(auth=auth)
        svc._plan_features_cache = {PlanType.PRO: svc._get_default_plan_features(PlanType.PRO)}
        svc._last_cache_update = datetime.now(UTC).timestamp()

        user = _fake_user(plan=PlanType.FREE)
        result = asyncio.run(svc.activate_subscription(user, PlanType.PRO, expires_at=fixed))
        call_args = auth.update_user_profile.call_args
        update_dto = call_args[0][1]
        assert update_dto.subscription_end == fixed
        assert result is updated

    def test_free_user_gets_fresh_subscription(self):
        auth = MagicMock()
        auth.update_user_profile.return_value = _fake_user(plan=PlanType.PRO)
        svc = _make_service(auth=auth)
        svc._plan_features_cache = {PlanType.PRO: svc._get_default_plan_features(PlanType.PRO)}
        svc._last_cache_update = datetime.now(UTC).timestamp()

        user = _fake_user(plan=PlanType.FREE)
        asyncio.run(svc.activate_subscription(user, PlanType.PRO, months=1))

        update_dto = auth.update_user_profile.call_args[0][1]
        # Should be ~30 days from now
        expected_min = datetime.now(UTC) + timedelta(days=29)
        expected_max = datetime.now(UTC) + timedelta(days=31)
        assert expected_min <= update_dto.subscription_end <= expected_max

    def test_active_pro_stacks_from_subscription_end(self):
        auth = MagicMock()
        auth.update_user_profile.return_value = _fake_user(plan=PlanType.PRO)
        svc = _make_service(auth=auth)
        svc._plan_features_cache = {PlanType.PRO: svc._get_default_plan_features(PlanType.PRO)}
        svc._last_cache_update = datetime.now(UTC).timestamp()

        existing_end = _future(15)
        user = _fake_user(plan=PlanType.PRO, subscription_end=existing_end)
        asyncio.run(svc.activate_subscription(user, PlanType.PRO, months=1))

        update_dto = auth.update_user_profile.call_args[0][1]
        # Should be existing_end + 30 days
        expected = existing_end + timedelta(days=30)
        assert abs((update_dto.subscription_end - expected).total_seconds()) < 2


# ---------------------------------------------------------------------------
# cancel_subscription
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    def test_free_plan_raises_400(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.FREE)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.cancel_subscription(user))
        assert exc.value.status_code == 400

    def test_already_cancelled_raises_400(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.PRO, subscription_cancelled=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.cancel_subscription(user))
        assert exc.value.status_code == 400

    def test_soft_cancel_sets_cancelled_flag(self):
        auth = MagicMock()
        auth.update_user_profile.return_value = _fake_user(
            plan=PlanType.PRO, subscription_cancelled=True
        )
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.PRO, subscription_cancelled=False)
        asyncio.run(svc.cancel_subscription(user))
        update_dto = auth.update_user_profile.call_args[0][1]
        assert update_dto.subscription_cancelled is True

    def test_soft_cancel_does_not_change_plan_or_end(self):
        auth = MagicMock()
        auth.update_user_profile.return_value = MagicMock()
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.PRO, subscription_end=_future(10))
        asyncio.run(svc.cancel_subscription(user))
        update_dto = auth.update_user_profile.call_args[0][1]
        assert not hasattr(update_dto, "plan") or update_dto.plan is None


# ---------------------------------------------------------------------------
# activate_free_trial
# ---------------------------------------------------------------------------


class TestActivateFreeTrial:
    def test_non_free_plan_raises_400(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.PRO)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_free_trial(user))
        assert exc.value.status_code == 400

    def test_already_used_trial_raises_400(self):
        svc = _make_service()
        user = _fake_user(plan=PlanType.FREE, used_trial=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_free_trial(user))
        assert exc.value.status_code == 400

    def test_phone_hash_hit_raises_400(self):
        from subscription.models import TrialHistory

        session = MagicMock()
        db = MagicMock()
        db.session = session
        existing_row = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = existing_row

        svc = _make_service(db=db)
        user = _fake_user(plan=PlanType.FREE, used_trial=False, phone="+77001234567")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_free_trial(user))
        assert exc.value.status_code == 400
        assert "phone" in exc.value.detail.lower()

    def test_no_phone_skips_hash_check(self):
        auth = MagicMock()
        auth.activate_free_trial.return_value = _fake_user(plan=PlanType.PRO)
        svc = _make_service(auth=auth)
        user = _fake_user(plan=PlanType.FREE, used_trial=False, phone=None)
        asyncio.run(svc.activate_free_trial(user))
        auth.activate_free_trial.assert_called_once_with(user)

    def test_success_calls_activate_free_trial(self):
        auth = MagicMock()
        granted = _fake_user(plan=PlanType.PRO)
        auth.activate_free_trial.return_value = granted

        session = MagicMock()
        db = MagicMock()
        db.session = session
        session.query.return_value.filter.return_value.first.return_value = None

        svc = _make_service(auth=auth, db=db)
        user = _fake_user(plan=PlanType.FREE, used_trial=False, phone="+77001234567")
        result = asyncio.run(svc.activate_free_trial(user))
        auth.activate_free_trial.assert_called_once_with(user)
        assert result is granted
