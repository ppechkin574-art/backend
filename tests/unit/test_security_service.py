"""Unit tests for SecurityService.

Covers pure static helpers (_fraud_event_to_dict, _risk_profile_to_dict,
_audit_log_to_dict) and mutation methods (mark_event_reviewed, restrict_user,
block_user, unrestrict_user) with mocked SQLAlchemy session.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import security.models  # noqa: F401 — ensure mapper registered

from security.service import SecurityService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> MagicMock:
    session = MagicMock()
    return session


def _make_service(session=None) -> SecurityService:
    return SecurityService(session=session or _make_session())


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def _fake_event(
    id: int = 1,
    user_id=None,
    device_id: str = "dev-1",
    ip_address: str = "1.2.3.4",
    endpoint: str = "/user/login",
    method: str = "POST",
    user_agent: str | None = None,
    event_type: str = "suspicious_login",
    reason: str = "too many attempts",
    risk_score: int = 75,
    event_metadata: dict | None = None,
    status: str = "open",
    created_at: datetime | None = None,
    reviewed_at: datetime | None = None,
    reviewed_by: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        user_id=user_id or uuid4(),
        device_id=device_id,
        ip_address=ip_address,
        endpoint=endpoint,
        method=method,
        user_agent=user_agent,
        event_type=event_type,
        reason=reason,
        risk_score=risk_score,
        event_metadata=event_metadata or {},
        status=status,
        created_at=created_at or _now(),
        reviewed_at=reviewed_at,
        reviewed_by=reviewed_by,
    )


def _fake_profile(
    id: int = 1,
    user_id=None,
    current_risk_score: int = 0,
    status: str = "normal",
    last_suspicious_activity_at: datetime | None = None,
    total_suspicious_events: int = 0,
    restricted_until: datetime | None = None,
    blocked_at: datetime | None = None,
    restriction_reason: str | None = None,
    is_watchlisted: bool = False,
    points_frozen: bool = False,
    referral_disabled: bool = False,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        user_id=user_id or uuid4(),
        current_risk_score=current_risk_score,
        status=status,
        last_suspicious_activity_at=last_suspicious_activity_at,
        total_suspicious_events=total_suspicious_events,
        restricted_until=restricted_until,
        blocked_at=blocked_at,
        restriction_reason=restriction_reason,
        is_watchlisted=is_watchlisted,
        points_frozen=points_frozen,
        referral_disabled=referral_disabled,
        created_at=created_at or _now(),
        updated_at=updated_at or _now(),
    )


def _fake_audit_log(
    id: int = 1,
    user_id=None,
    points_before: int = 100,
    points_after: int = 150,
    points_delta: int = 50,
    source_type: str = "ent_attempt",
    source_id: str = "42",
    reason: str | None = None,
    is_suspicious: bool = False,
    fraud_event_id: int | None = None,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        user_id=user_id or uuid4(),
        points_before=points_before,
        points_after=points_after,
        points_delta=points_delta,
        source_type=source_type,
        source_id=source_id,
        reason=reason,
        is_suspicious=is_suspicious,
        fraud_event_id=fraud_event_id,
        created_at=created_at or _now(),
    )


# ---------------------------------------------------------------------------
# _fraud_event_to_dict
# ---------------------------------------------------------------------------


class TestFraudEventToDict:
    def test_basic_fields(self):
        user_id = uuid4()
        event = _fake_event(id=7, user_id=user_id, risk_score=80, status="open")
        result = SecurityService._fraud_event_to_dict(event)
        assert result["id"] == 7
        assert result["user_id"] == str(user_id)
        assert result["risk_score"] == 80
        assert result["status"] == "open"

    def test_no_user_id_returns_none(self):
        event = _fake_event(user_id=None)
        # user_id=None → str(None) would be "None" — let's check actual logic
        event.user_id = None
        result = SecurityService._fraud_event_to_dict(event)
        assert result["user_id"] is None

    def test_reviewed_at_isoformat(self):
        reviewed = datetime(2026, 6, 13, 14, 0, 0, tzinfo=UTC)
        event = _fake_event(reviewed_at=reviewed, reviewed_by="admin@aima.kz")
        result = SecurityService._fraud_event_to_dict(event)
        assert result["reviewed_at"] == reviewed.isoformat()
        assert result["reviewed_by"] == "admin@aima.kz"

    def test_no_reviewed_at_returns_none(self):
        event = _fake_event(reviewed_at=None)
        result = SecurityService._fraud_event_to_dict(event)
        assert result["reviewed_at"] is None

    def test_metadata_key(self):
        meta = {"foo": "bar"}
        event = _fake_event(event_metadata=meta)
        result = SecurityService._fraud_event_to_dict(event)
        assert result["metadata"] == meta

    def test_created_at_isoformat(self):
        ts = _now()
        event = _fake_event(created_at=ts)
        result = SecurityService._fraud_event_to_dict(event)
        assert result["created_at"] == ts.isoformat()


# ---------------------------------------------------------------------------
# _risk_profile_to_dict
# ---------------------------------------------------------------------------


class TestRiskProfileToDict:
    def test_basic_fields(self):
        user_id = uuid4()
        profile = _fake_profile(id=3, user_id=user_id, current_risk_score=50, status="restricted")
        result = SecurityService._risk_profile_to_dict(profile)
        assert result["id"] == 3
        assert result["user_id"] == str(user_id)
        assert result["current_risk_score"] == 50
        assert result["status"] == "restricted"

    def test_none_dates_return_none(self):
        profile = _fake_profile(
            blocked_at=None,
            last_suspicious_activity_at=None,
            restricted_until=None,
        )
        result = SecurityService._risk_profile_to_dict(profile)
        assert result["blocked_at"] is None
        assert result["last_suspicious_activity_at"] is None
        assert result["restricted_until"] is None

    def test_dates_isoformat(self):
        ts = _now()
        profile = _fake_profile(blocked_at=ts, restricted_until=ts + timedelta(days=7))
        result = SecurityService._risk_profile_to_dict(profile)
        assert result["blocked_at"] == ts.isoformat()
        assert result["restricted_until"] == (ts + timedelta(days=7)).isoformat()

    def test_no_user_id_returns_none(self):
        profile = _fake_profile(user_id=None)
        profile.user_id = None
        result = SecurityService._risk_profile_to_dict(profile)
        assert result["user_id"] is None


# ---------------------------------------------------------------------------
# _audit_log_to_dict
# ---------------------------------------------------------------------------


class TestAuditLogToDict:
    def test_basic_fields(self):
        user_id = uuid4()
        log = _fake_audit_log(
            id=5, user_id=user_id, points_before=100, points_after=200, points_delta=100
        )
        result = SecurityService._audit_log_to_dict(log)
        assert result["id"] == 5
        assert result["user_id"] == str(user_id)
        assert result["points_before"] == 100
        assert result["points_after"] == 200
        assert result["points_delta"] == 100

    def test_not_suspicious(self):
        log = _fake_audit_log(is_suspicious=False)
        result = SecurityService._audit_log_to_dict(log)
        assert result["is_suspicious"] is False

    def test_suspicious_flag(self):
        log = _fake_audit_log(is_suspicious=True, fraud_event_id=99)
        result = SecurityService._audit_log_to_dict(log)
        assert result["is_suspicious"] is True
        assert result["fraud_event_id"] == 99


# ---------------------------------------------------------------------------
# mark_event_reviewed
# ---------------------------------------------------------------------------


class TestMarkEventReviewed:
    def test_sets_status_reviewed(self):
        event = _fake_event(id=1, status="open")
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = event
        svc = _make_service(session)
        svc.mark_event_reviewed(1, "admin@aima.kz")
        assert event.status == "reviewed"
        assert event.reviewed_by == "admin@aima.kz"
        assert event.reviewed_at is not None
        session.commit.assert_called_once()

    def test_not_found_noop(self):
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = None
        svc = _make_service(session)
        svc.mark_event_reviewed(999, "admin")
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# restrict_user
# ---------------------------------------------------------------------------


class TestRestrictUser:
    def test_sets_status_restricted(self):
        profile = _fake_profile(status="normal")
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = profile
        svc = _make_service(session)
        svc.restrict_user(uuid4(), reason="spam", until=None)
        assert profile.status == "restricted"
        assert profile.restriction_reason == "spam"
        session.commit.assert_called_once()

    def test_sets_restricted_until(self):
        until = _now() + timedelta(days=7)
        profile = _fake_profile()
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = profile
        svc = _make_service(session)
        svc.restrict_user(uuid4(), reason="test", until=until)
        assert profile.restricted_until == until


# ---------------------------------------------------------------------------
# block_user
# ---------------------------------------------------------------------------


class TestBlockUser:
    def test_sets_status_blocked(self):
        profile = _fake_profile(status="normal")
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = profile
        svc = _make_service(session)
        svc.block_user(uuid4(), reason="fraud")
        assert profile.status == "blocked"
        assert profile.restriction_reason == "fraud"
        assert profile.blocked_at is not None
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# unrestrict_user
# ---------------------------------------------------------------------------


class TestUnrestrictUser:
    def test_clears_restriction(self):
        profile = _fake_profile(
            status="restricted",
            restriction_reason="spam",
            restricted_until=_now() + timedelta(days=3),
        )
        session = _make_session()
        session.query.return_value.filter.return_value.first.return_value = profile
        svc = _make_service(session)
        svc.unrestrict_user(uuid4())
        assert profile.status == "normal"
        assert profile.restricted_until is None
        assert profile.restriction_reason is None
        session.commit.assert_called_once()
