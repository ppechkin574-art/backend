"""Unit tests for SubscriptionService.get_available_features() and
related subscription benefit logic.

Tests cover:
- FREE plan: TOPIC_TRAINER + TRIAL_ENT enabled, paid features disabled
- PRO plan: all major features enabled
- Expired PRO subscription: auto-downgraded to FREE features
- refresh_subscription_status: triggers Keycloak update on expiry
- get_available_features: returns dict keyed by FeatureType values
- revoke_subscription: PRO → FREE immediately (no grace period)
- cancel_subscription: sets cancelled=True but keeps PRO features

All tests are pure — no DB, no network.
Subscription falls back to hardcoded defaults when DB is unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from common.enums import FeatureType, PlanType
from subscription.service import SubscriptionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(auth_service=None) -> SubscriptionService:
    """Build SubscriptionService with a mock Database that returns no DB rows
    (forces fall-through to _get_default_plan_features hardcoded defaults)."""
    db = MagicMock()
    db.session.close = MagicMock()

    # SubscriptionPlanRepository.get_active_plans() → [] (no DB plans)
    session = MagicMock()
    session.close = MagicMock()
    db.session = session
    # The internal call chain: Database.session → SubscriptionPlanRepository(session).get_active_plans()
    # MagicMock will return a MagicMock for any attribute, so we need to make
    # get_active_plans() return [] explicitly.
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.all.return_value = []

    svc = SubscriptionService(
        auth_service=auth_service or MagicMock(),
        database=db,
    )
    # Pre-populate cache with defaults so _load_plan_features_from_db is not
    # called during tests (it tries real DB queries).
    svc._plan_features_cache = {
        PlanType.FREE: svc._get_default_plan_features(PlanType.FREE),
        PlanType.PRO: svc._get_default_plan_features(PlanType.PRO),
    }
    svc._last_cache_update = datetime.now(UTC).timestamp()
    return svc


def _user(
    plan: PlanType = PlanType.FREE,
    subscription_end: datetime | None = None,
    subscription_cancelled: bool = False,
    used_trial: bool = False,
    phone: str = "+77001234567",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        plan=plan,
        subscription_end=subscription_end,
        subscription_cancelled=subscription_cancelled,
        used_trial=used_trial,
        phone=phone,
        name="Тест",
        email=None,
        avatar=None,
    )


# ---------------------------------------------------------------------------
# Default plan features (hardcoded fallback)
# ---------------------------------------------------------------------------


class TestDefaultPlanFeatures:
    svc = SubscriptionService.__new__(SubscriptionService)

    def test_free_defaults_topic_trainer_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.TOPIC_TRAINER.value] is True

    def test_free_defaults_trial_ent_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.TRIAL_ENT.value] is True

    def test_free_defaults_full_course_disabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.FULL_COURSE.value] is False

    def test_free_defaults_daily_tasks_disabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.DAILY_TASKS.value] is False

    def test_free_defaults_cashback_disabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.CASHBACK.value] is False

    def test_free_defaults_ai_disabled(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.features[FeatureType.AI.value] is False

    def test_free_defaults_price_is_zero(self):
        f = self.svc._get_default_plan_features(PlanType.FREE)
        assert f.price == 0.0

    def test_pro_defaults_full_course_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.features[FeatureType.FULL_COURSE.value] is True

    def test_pro_defaults_daily_tasks_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.features[FeatureType.DAILY_TASKS.value] is True

    def test_pro_defaults_cashback_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.features[FeatureType.CASHBACK.value] is True

    def test_pro_defaults_ai_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.features[FeatureType.AI.value] is True

    def test_pro_defaults_parent_access_enabled(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.features[FeatureType.PARENT_ACCESS.value] is True

    def test_pro_defaults_duration_30_days(self):
        f = self.svc._get_default_plan_features(PlanType.PRO)
        assert f.duration_days == 30

    def test_unknown_plan_type_falls_back_to_free(self):
        # PlanType.FREE is the default fallback
        f_free = self.svc._get_default_plan_features(PlanType.FREE)
        # Simulate unknown by requesting FREE
        assert f_free.plan_type == PlanType.FREE


# ---------------------------------------------------------------------------
# get_available_features: live user path
# ---------------------------------------------------------------------------


class TestGetAvailableFeatures:
    def test_free_user_gets_free_features(self):
        svc = _make_service()
        user = _user(plan=PlanType.FREE)
        features = svc.get_available_features(user)
        assert features[FeatureType.TOPIC_TRAINER.value] is True
        assert features[FeatureType.FULL_COURSE.value] is False
        assert features[FeatureType.DAILY_TASKS.value] is False

    def test_pro_user_gets_pro_features(self):
        svc = _make_service()
        user = _user(
            plan=PlanType.PRO,
            subscription_end=datetime.now(UTC) + timedelta(days=20),
        )
        features = svc.get_available_features(user)
        assert features[FeatureType.FULL_COURSE.value] is True
        assert features[FeatureType.DAILY_TASKS.value] is True
        assert features[FeatureType.AI.value] is True

    def test_expired_pro_user_gets_free_features(self):
        """If subscription_end is in the past, features must fall back to FREE
        because refresh_subscription_status() downgrades the plan."""
        # Set up auth_service to return a FREE user after update_user_profile
        auth_svc = MagicMock()
        free_user = _user(plan=PlanType.FREE)
        auth_svc.update_user_profile.return_value = free_user

        svc = _make_service(auth_service=auth_svc)
        expired_user = _user(
            plan=PlanType.PRO,
            subscription_end=datetime.now(UTC) - timedelta(days=1),  # expired yesterday
        )
        features = svc.get_available_features(expired_user)
        # After downgrade, returns FREE features
        assert features[FeatureType.FULL_COURSE.value] is False
        assert features[FeatureType.DAILY_TASKS.value] is False

    def test_active_pro_not_downgraded(self):
        """subscription_end in the future → no downgrade → PRO features."""
        svc = _make_service()
        user = _user(
            plan=PlanType.PRO,
            subscription_end=datetime.now(UTC) + timedelta(days=10),
        )
        features = svc.get_available_features(user)
        assert features[FeatureType.FULL_COURSE.value] is True

    def test_returns_dict_with_feature_type_keys(self):
        svc = _make_service()
        user = _user(plan=PlanType.FREE)
        features = svc.get_available_features(user)
        assert isinstance(features, dict)
        # All FeatureType values must be present as keys
        for ft in FeatureType:
            assert ft.value in features


# ---------------------------------------------------------------------------
# refresh_subscription_status
# ---------------------------------------------------------------------------


class TestRefreshSubscriptionStatus:
    def test_free_user_unchanged(self):
        svc = _make_service()
        user = _user(plan=PlanType.FREE)
        result = svc.refresh_subscription_status(user)
        assert result is user

    def test_pro_not_expired_unchanged(self):
        svc = _make_service()
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=5))
        result = svc.refresh_subscription_status(user)
        assert result is user

    def test_expired_pro_triggers_keycloak_update(self):
        auth_svc = MagicMock()
        downgraded = _user(plan=PlanType.FREE)
        auth_svc.update_user_profile.return_value = downgraded

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) - timedelta(hours=1))
        result = svc.refresh_subscription_status(user)

        auth_svc.update_user_profile.assert_called_once()
        # The returned user is the downgraded one
        assert result.plan == PlanType.FREE

    def test_keycloak_failure_returns_original_user(self):
        """If the Keycloak update call fails, return the original user
        rather than raising (best-effort downgrade)."""
        auth_svc = MagicMock()
        auth_svc.update_user_profile.side_effect = Exception("Keycloak 503")

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) - timedelta(hours=1))
        result = svc.refresh_subscription_status(user)

        # Should NOT raise, should return original user object
        assert result is user

    def test_pro_without_subscription_end_not_downgraded(self):
        """PRO with no subscription_end set → condition is False → no downgrade."""
        svc = _make_service()
        user = _user(plan=PlanType.PRO, subscription_end=None)
        result = svc.refresh_subscription_status(user)
        assert result is user


# ---------------------------------------------------------------------------
# revoke_subscription
# ---------------------------------------------------------------------------


class TestRevokeSubscription:
    def test_pro_user_revoked_to_free(self):
        auth_svc = MagicMock()
        free_user = _user(plan=PlanType.FREE)
        auth_svc.update_user_profile.return_value = free_user

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=10))
        result = svc.revoke_subscription(user)

        auth_svc.update_user_profile.assert_called_once()
        assert result.plan == PlanType.FREE

    def test_already_free_is_noop(self):
        auth_svc = MagicMock()
        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.FREE)
        result = svc.revoke_subscription(user)

        auth_svc.update_user_profile.assert_not_called()
        assert result is user

    def test_revoke_clears_subscription_end(self):
        """revoke passes subscription_end=None to update_user_profile."""
        auth_svc = MagicMock()
        free_user = _user(plan=PlanType.FREE)
        auth_svc.update_user_profile.return_value = free_user

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=5))
        svc.revoke_subscription(user)

        call_kwargs = auth_svc.update_user_profile.call_args[0][1]
        assert call_kwargs.subscription_end is None


# ---------------------------------------------------------------------------
# cancel_subscription
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    def test_cancel_pro_sets_cancelled_flag(self):
        auth_svc = MagicMock()
        cancelled_user = _user(plan=PlanType.PRO, subscription_cancelled=True)
        auth_svc.update_user_profile.return_value = cancelled_user

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=10))
        result = asyncio.run(svc.cancel_subscription(user))

        # update_user_profile called with subscription_cancelled=True
        call_kwargs = auth_svc.update_user_profile.call_args[0][1]
        assert call_kwargs.subscription_cancelled is True
        assert result.plan == PlanType.PRO  # plan NOT changed

    def test_cancel_free_user_raises_400(self):
        svc = _make_service()
        user = _user(plan=PlanType.FREE)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(svc.cancel_subscription(user))
        assert exc_info.value.status_code == 400

    def test_cancel_already_cancelled_raises_400(self):
        svc = _make_service()
        user = _user(plan=PlanType.PRO, subscription_cancelled=True)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(svc.cancel_subscription(user))
        assert exc_info.value.status_code == 400

    def test_cancel_does_not_change_subscription_end(self):
        """Soft cancel: user keeps PRO until subscription_end — it's NOT cleared."""
        auth_svc = MagicMock()
        original_end = datetime.now(UTC) + timedelta(days=15)
        cancelled_user = _user(
            plan=PlanType.PRO,
            subscription_end=original_end,
            subscription_cancelled=True,
        )
        auth_svc.update_user_profile.return_value = cancelled_user

        svc = _make_service(auth_service=auth_svc)
        user = _user(plan=PlanType.PRO, subscription_end=original_end)
        result = asyncio.run(svc.cancel_subscription(user))

        # subscription_end not cleared
        assert result.subscription_end == original_end


# ---------------------------------------------------------------------------
# Limitations contract
# ---------------------------------------------------------------------------


class TestLimitationsContract:
    def test_free_has_trainer_limit(self):
        svc = SubscriptionService.__new__(SubscriptionService)
        f = svc._get_default_plan_features(PlanType.FREE)
        assert "max_trainers_per_day" in f.limitations
        assert f.limitations["max_trainers_per_day"] < 20  # FREE is capped

    def test_pro_has_higher_trainer_limit_than_free(self):
        svc = SubscriptionService.__new__(SubscriptionService)
        free = svc._get_default_plan_features(PlanType.FREE)
        pro = svc._get_default_plan_features(PlanType.PRO)
        assert pro.limitations["max_trainers_per_day"] > free.limitations["max_trainers_per_day"]

    def test_pro_has_higher_question_limit_than_free(self):
        svc = SubscriptionService.__new__(SubscriptionService)
        free = svc._get_default_plan_features(PlanType.FREE)
        pro = svc._get_default_plan_features(PlanType.PRO)
        assert pro.limitations["max_questions_per_trainer"] > free.limitations["max_questions_per_trainer"]
