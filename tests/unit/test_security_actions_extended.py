"""Extended unit tests for SecurityService — IDP interactions and profile creation.

Covers what test_security_service.py and test_admin_actions.py don't:
- _get_or_create_profile: existing vs. new-profile paths
- block_user: IDP set_active(False) called, swallowed on error, skipped when no IDP
- unrestrict_user: IDP set_active(True) only when was blocked, swallowed on error
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from security.service import SecurityService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> MagicMock:
    return MagicMock()


def _fake_profile(**kwargs):
    defaults = dict(
        id=1,
        user_id=uuid4(),
        status="normal",
        restriction_reason=None,
        restricted_until=None,
        blocked_at=None,
        is_watchlisted=False,
        points_frozen=False,
        referral_disabled=False,
        current_risk_score=0,
        total_suspicious_events=0,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    return ns


def _session_with_profile(profile):
    """Return a session whose query().filter().first() yields `profile`."""
    session = _make_session()
    session.query.return_value.filter.return_value.first.return_value = profile
    return session


# ---------------------------------------------------------------------------
# _get_or_create_profile
# ---------------------------------------------------------------------------

class TestGetOrCreateProfile:
    def test_returns_existing_profile_without_add(self):
        profile = _fake_profile()
        session = _session_with_profile(profile)
        svc = SecurityService(session=session)

        result = svc._get_or_create_profile(profile.user_id)

        assert result is profile
        session.add.assert_not_called()
        session.flush.assert_not_called()

    def test_creates_new_profile_when_not_found(self):
        session = _session_with_profile(None)
        svc = SecurityService(session=session)
        user_id = uuid4()

        from security.models import UserRiskProfile

        result = svc._get_or_create_profile(user_id)

        assert isinstance(result, UserRiskProfile)
        assert result.user_id == user_id
        session.add.assert_called_once_with(result)
        session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# block_user + IDP
# ---------------------------------------------------------------------------

class TestBlockUserIDP:
    def test_calls_idp_set_active_false(self):
        profile = _fake_profile(status="normal")
        session = _session_with_profile(profile)
        idp = MagicMock()
        svc = SecurityService(session=session, identity_provider=idp)
        user_id = uuid4()

        svc.block_user(user_id, reason="fraud detected")

        idp.set_active.assert_called_once_with(user_id, False)

    def test_no_idp_block_works_without_crash(self):
        profile = _fake_profile(status="normal")
        session = _session_with_profile(profile)
        svc = SecurityService(session=session, identity_provider=None)

        svc.block_user(uuid4(), reason="fraud")

        assert profile.status == "blocked"

    def test_idp_exception_is_swallowed(self):
        profile = _fake_profile(status="normal")
        session = _session_with_profile(profile)
        idp = MagicMock()
        idp.set_active.side_effect = RuntimeError("keycloak down")
        svc = SecurityService(session=session, identity_provider=idp)

        # Must NOT raise even if Keycloak is unreachable
        svc.block_user(uuid4(), reason="fraud")

        assert profile.status == "blocked"
        session.commit.assert_called_once()

    def test_commit_happens_before_idp_call(self):
        """DB commit must persist the block even if IDP call fails."""
        profile = _fake_profile(status="normal")
        session = _session_with_profile(profile)
        call_order = []
        session.commit.side_effect = lambda: call_order.append("commit")
        idp = MagicMock()
        idp.set_active.side_effect = lambda *a: call_order.append("idp")
        svc = SecurityService(session=session, identity_provider=idp)

        svc.block_user(uuid4(), reason="fraud")

        assert call_order == ["commit", "idp"]


# ---------------------------------------------------------------------------
# unrestrict_user + IDP
# ---------------------------------------------------------------------------

class TestUnrestrictUserIDP:
    def test_calls_idp_set_active_true_when_was_blocked(self):
        profile = _fake_profile(status="blocked")
        session = _session_with_profile(profile)
        idp = MagicMock()
        svc = SecurityService(session=session, identity_provider=idp)
        user_id = uuid4()

        svc.unrestrict_user(user_id)

        idp.set_active.assert_called_once_with(user_id, True)

    def test_no_idp_call_when_was_restricted_not_blocked(self):
        profile = _fake_profile(status="restricted", restriction_reason="spam")
        session = _session_with_profile(profile)
        idp = MagicMock()
        svc = SecurityService(session=session, identity_provider=idp)

        svc.unrestrict_user(uuid4())

        idp.set_active.assert_not_called()
        assert profile.status == "normal"

    def test_idp_exception_on_unblock_is_swallowed(self):
        profile = _fake_profile(status="blocked")
        session = _session_with_profile(profile)
        idp = MagicMock()
        idp.set_active.side_effect = RuntimeError("keycloak down")
        svc = SecurityService(session=session, identity_provider=idp)

        svc.unrestrict_user(uuid4())

        assert profile.status == "normal"
        session.commit.assert_called_once()

    def test_no_idp_provided_unblock_works(self):
        profile = _fake_profile(status="blocked")
        session = _session_with_profile(profile)
        svc = SecurityService(session=session, identity_provider=None)

        svc.unrestrict_user(uuid4())

        assert profile.status == "normal"


# ---------------------------------------------------------------------------
# get_events — filter application
# ---------------------------------------------------------------------------

class TestGetEventsFilters:
    def _make_svc_with_events(self, events: list) -> SecurityService:
        """Wire session so that get_events() returns the given event list."""
        session = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.count.return_value = len(events)
        q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = events
        session.query.return_value = q
        return SecurityService(session=session)

    def test_returns_correct_structure(self):
        from types import SimpleNamespace
        from datetime import UTC, datetime

        event = SimpleNamespace(
            id=1, user_id=uuid4(), device_id=None, ip_address="1.2.3.4",
            endpoint="/quiz/answer", method="POST", user_agent=None,
            event_type="rapid_points_farm", reason="too fast", risk_score=85,
            event_metadata={}, status="open",
            created_at=datetime.now(tz=UTC), reviewed_at=None, reviewed_by=None,
        )
        svc = self._make_svc_with_events([event])

        result = svc.get_events(status="open", min_risk=50)

        assert result["total"] == 1
        assert result["page"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["risk_score"] == 85

    def test_empty_result_when_no_events(self):
        svc = self._make_svc_with_events([])

        result = svc.get_events()

        assert result["total"] == 0
        assert result["items"] == []


# ---------------------------------------------------------------------------
# Notification-policy proof: block_user does NOT auto-block — it's always
# called explicitly (this test documents the architectural guarantee).
# ---------------------------------------------------------------------------

class TestNoAutoBlock:
    """Verify that SecurityService never calls block_user() internally
    from detectors — it must only be called by an explicit admin action."""

    def test_block_user_has_no_internal_callers_in_service(self):
        import inspect
        src = inspect.getsource(SecurityService)
        # Count how many times block_user appears: definition + calls
        # definition is "def block_user" — all others would be internal calls
        lines = [l.strip() for l in src.splitlines() if "block_user" in l]
        definitions = [l for l in lines if l.startswith("def block_user")]
        calls = [l for l in lines if "self.block_user(" in l or "svc.block_user(" in l]
        # The service must define block_user but never call it on itself
        assert len(definitions) == 1, "Expected exactly one block_user definition"
        assert len(calls) == 0, f"block_user auto-called internally: {calls}"
