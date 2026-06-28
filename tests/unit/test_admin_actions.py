"""Unit tests for SecurityService admin action methods."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from security.models import FraudEvent, UserRiskProfile
from security.service import SecurityService


USER_ID = uuid4()


def _make_profile(**kwargs) -> UserRiskProfile:
    defaults = dict(
        id=1,
        user_id=USER_ID,
        current_risk_score=50,
        status="normal",
        last_suspicious_activity_at=None,
        total_suspicious_events=3,
        restricted_until=None,
        blocked_at=None,
        restriction_reason=None,
        is_watchlisted=False,
        points_frozen=False,
        referral_disabled=False,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    defaults.update(kwargs)
    profile = MagicMock(spec=UserRiskProfile)
    for k, v in defaults.items():
        setattr(profile, k, v)
    return profile


def _make_service(profile=None):
    session = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = profile or _make_profile()
    query_mock.filter.return_value = filter_mock
    session.query.return_value = query_mock
    return SecurityService(session=session), session


# ------------------------------------------------------------------
# set_watchlist
# ------------------------------------------------------------------


class TestSetWatchlist:
    def test_add_to_watchlist(self):
        profile = _make_profile(is_watchlisted=False)
        svc, session = _make_service(profile)

        svc.set_watchlist(USER_ID, watchlisted=True, admin_username="admin1")

        assert profile.is_watchlisted is True
        session.add.assert_called_once()  # admin_action event
        session.commit.assert_called_once()

    def test_remove_from_watchlist(self):
        profile = _make_profile(is_watchlisted=True)
        svc, session = _make_service(profile)

        svc.set_watchlist(USER_ID, watchlisted=False, admin_username="admin1")

        assert profile.is_watchlisted is False
        session.commit.assert_called_once()

    def test_admin_action_event_logged(self):
        profile = _make_profile()
        svc, session = _make_service(profile)

        svc.set_watchlist(USER_ID, watchlisted=True, admin_username="boss")

        added = session.add.call_args[0][0]
        assert isinstance(added, FraudEvent)
        assert added.event_type == "admin_action"
        assert "watchlist_add" in added.reason
        assert added.reviewed_by == "boss"


# ------------------------------------------------------------------
# set_points_frozen
# ------------------------------------------------------------------


class TestSetPointsFrozen:
    def test_freeze_points(self):
        profile = _make_profile(points_frozen=False)
        svc, session = _make_service(profile)

        svc.set_points_frozen(USER_ID, frozen=True, admin_username="admin1")

        assert profile.points_frozen is True
        session.commit.assert_called_once()

    def test_unfreeze_points(self):
        profile = _make_profile(points_frozen=True)
        svc, session = _make_service(profile)

        svc.set_points_frozen(USER_ID, frozen=False, admin_username="admin1")

        assert profile.points_frozen is False
        session.commit.assert_called_once()

    def test_freeze_logs_correct_action(self):
        profile = _make_profile()
        svc, session = _make_service(profile)

        svc.set_points_frozen(USER_ID, frozen=True, admin_username="boss")

        event = session.add.call_args[0][0]
        assert "points_freeze" in event.reason

    def test_unfreeze_logs_correct_action(self):
        profile = _make_profile(points_frozen=True)
        svc, session = _make_service(profile)

        svc.set_points_frozen(USER_ID, frozen=False, admin_username="boss")

        event = session.add.call_args[0][0]
        assert "points_unfreeze" in event.reason


# ------------------------------------------------------------------
# set_referral_disabled
# ------------------------------------------------------------------


class TestSetReferralDisabled:
    def test_disable_referral(self):
        profile = _make_profile(referral_disabled=False)
        svc, session = _make_service(profile)

        svc.set_referral_disabled(USER_ID, disabled=True, admin_username="admin1")

        assert profile.referral_disabled is True
        session.commit.assert_called_once()

    def test_enable_referral(self):
        profile = _make_profile(referral_disabled=True)
        svc, session = _make_service(profile)

        svc.set_referral_disabled(USER_ID, disabled=False, admin_username="admin1")

        assert profile.referral_disabled is False

    def test_logs_referral_disable(self):
        profile = _make_profile()
        svc, session = _make_service(profile)

        svc.set_referral_disabled(USER_ID, disabled=True, admin_username="boss")

        event = session.add.call_args[0][0]
        assert "referral_disable" in event.reason

    def test_logs_referral_enable(self):
        profile = _make_profile(referral_disabled=True)
        svc, session = _make_service(profile)

        svc.set_referral_disabled(USER_ID, disabled=False, admin_username="boss")

        event = session.add.call_args[0][0]
        assert "referral_enable" in event.reason


# ------------------------------------------------------------------
# reset_risk_score
# ------------------------------------------------------------------


class TestResetRiskScore:
    def test_resets_score_and_events(self):
        profile = _make_profile(current_risk_score=80, total_suspicious_events=5)
        svc, session = _make_service(profile)

        svc.reset_risk_score(USER_ID, admin_username="admin1")

        assert profile.current_risk_score == 0
        assert profile.total_suspicious_events == 0
        session.commit.assert_called_once()

    def test_logs_admin_action(self):
        profile = _make_profile(current_risk_score=80)
        svc, session = _make_service(profile)

        svc.reset_risk_score(USER_ID, admin_username="boss")

        event = session.add.call_args[0][0]
        assert event.event_type == "admin_action"
        assert "reset_risk_score" in event.reason


# ------------------------------------------------------------------
# mark_event_false_positive
# ------------------------------------------------------------------


class TestMarkEventFalsePositive:
    def test_sets_status_false_positive(self):
        session = MagicMock()
        event = MagicMock(spec=FraudEvent)
        event.status = "open"
        session.query.return_value.filter.return_value.first.return_value = event

        svc = SecurityService(session=session)
        svc.mark_event_false_positive(event_id=42, reviewed_by="admin1")

        assert event.status == "false_positive"
        assert event.reviewed_by == "admin1"
        assert event.reviewed_at is not None
        session.commit.assert_called_once()

    def test_no_op_when_event_not_found(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        svc = SecurityService(session=session)
        svc.mark_event_false_positive(event_id=999, reviewed_by="admin1")

        session.commit.assert_not_called()


# ------------------------------------------------------------------
# risk_profile_to_dict — new fields included
# ------------------------------------------------------------------


class TestRiskProfileToDictNewFields:
    def test_new_fields_present(self):
        profile = _make_profile(is_watchlisted=True, points_frozen=True, referral_disabled=False)

        result = SecurityService._risk_profile_to_dict(profile)

        assert result["is_watchlisted"] is True
        assert result["points_frozen"] is True
        assert result["referral_disabled"] is False
