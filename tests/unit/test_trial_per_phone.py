"""Phone-hash trial blacklist + activate_free_trial wiring.

Covers:
- _hash_phone is deterministic + non-reversible (sha256 hex length 64).
- Different phones → different hashes.
- activate_free_trial refuses when phone is already in trial_history.
- activate_free_trial preserves existing user.used_trial check.
- activate_free_trial preserves existing plan != FREE rejection.
- After successful auth_service.activate_free_trial → row inserted.
- DB write failure on insert does NOT roll back the user-facing
  grant (the used_trial Keycloak attribute still works as primary).
- User without phone (email-only) skips the phone-hash layer entirely.
"""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from auth.dtos.users import UserDTO
from common.enums import PlanType

# Importing payments + promocode models eagerly so SQLAlchemy can
# resolve Subscription.payment / promocode_usage relationships when
# we instantiate TrialHistory. Without this, mapper init fails with
# "expression 'Payment' failed to locate a name" at test collection.
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401

from subscription.models import TrialHistory
from subscription.service import SubscriptionService, _hash_phone


# ─────────────────────────── hash function ───────────────────────────


def test_hash_phone_is_deterministic():
    assert _hash_phone("+77787943760") == _hash_phone("+77787943760")


def test_hash_phone_64_hex_chars():
    """sha256 → 32 bytes → 64 hex chars."""
    h = _hash_phone("+77787943760")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_phone_distinguishes_different_numbers():
    a = _hash_phone("+77787943760")
    b = _hash_phone("+77001234567")
    assert a != b


def test_hash_phone_is_case_sensitive_byte_level():
    """Different bytes → different hash. Make sure normalization is the
    caller's job, not the hasher's — we don't want the hash function
    silently equating two near-duplicates."""
    a = _hash_phone("+77787943760")
    b = _hash_phone("77787943760")
    assert a != b


# ─────────────────────────── activate_free_trial flow ───────────────────────────


class _FakeSession:
    def __init__(self, existing_rows: list[TrialHistory] | None = None, insert_fails: bool = False):
        self._existing = existing_rows or []
        self._insert_fails = insert_fails
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self._existing)

    def add(self, row):
        if self._insert_fails:
            raise RuntimeError("simulated DB write failure")
        self.added.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _FakeQuery:
    def __init__(self, rows: list[TrialHistory]):
        self._rows = rows

    def filter(self, *_args):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDatabase:
    def __init__(self, *, existing_rows=None, insert_fails=False):
        self._sessions: list[_FakeSession] = []
        self._existing = existing_rows or []
        self._insert_fails = insert_fails

    @property
    def session(self) -> _FakeSession:
        # New session per access — mirrors real SessionLocal() behaviour
        s = _FakeSession(self._existing, self._insert_fails)
        self._sessions.append(s)
        return s


class _FakeAuthService:
    def __init__(self):
        self.activate_calls: list[UserDTO] = []

    def activate_free_trial(self, user: UserDTO) -> UserDTO:
        self.activate_calls.append(user)
        # Return user with trial flag toggled (real impl does this in Keycloak)
        return user.model_copy(update={"used_trial": True})


def _make_user(
    *,
    phone: str | None = "+77787943760",
    plan: PlanType = PlanType.FREE,
    used_trial: bool = False,
) -> UserDTO:
    return UserDTO(
        id=uuid4(),
        username="test-user",
        name="Test User",
        email="test@example.com",
        phone=phone,
        plan=plan,
        used_trial=used_trial,
        is_active=True,
    )


def _make_service(db: _FakeDatabase, auth: _FakeAuthService) -> SubscriptionService:
    return SubscriptionService(auth_service=auth, database=db)


@pytest.mark.asyncio
async def test_grants_trial_when_phone_not_blacklisted():
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(phone="+77787943760")

    result = await service.activate_free_trial(user)

    assert result.used_trial is True
    assert len(auth.activate_calls) == 1
    # Hash row was inserted (second session created for the insert)
    assert any(s.added for s in db._sessions), "expected a TrialHistory row to be added"


@pytest.mark.asyncio
async def test_rejects_when_phone_in_trial_history():
    """The whole point of the layer — Keycloak user deleted then
    recreated on the same phone should NOT redeem a second trial."""
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(phone="+77787943760", used_trial=False)

    with pytest.raises(HTTPException) as exc:
        await service.activate_free_trial(user)

    assert exc.value.status_code == 400
    assert "trial already used" in exc.value.detail.lower()
    # auth_service was NOT called — short-circuited at phone-hash check
    assert auth.activate_calls == []


@pytest.mark.asyncio
async def test_rejects_when_user_used_trial_attribute_is_true():
    """Primary check stays in place — even if phone-hash table is empty
    (fresh user record, but used_trial set elsewhere), we still refuse."""
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(phone="+77787943760", used_trial=True)

    with pytest.raises(HTTPException) as exc:
        await service.activate_free_trial(user)

    assert exc.value.status_code == 400
    assert "trial already used" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_rejects_when_plan_already_pro():
    """Existing guard — don't allow trial on top of paid subscription."""
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(plan=PlanType.PRO)

    with pytest.raises(HTTPException) as exc:
        await service.activate_free_trial(user)

    assert exc.value.status_code == 400
    assert "active subscription" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_user_without_phone_skips_phone_hash_layer():
    """Email-only registrations have user.phone = None. The phone-hash
    layer must not trip on None — fall through to existing checks only."""
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(phone=None)

    result = await service.activate_free_trial(user)

    assert result.used_trial is True
    assert len(auth.activate_calls) == 1


@pytest.mark.asyncio
async def test_db_insert_failure_does_not_break_user_flow():
    """If we can't record the hash for some reason (DB hiccup), the
    user-facing grant still completes — used_trial on the Keycloak user
    is the primary defence. We log and rollback the trial_history insert."""
    db = _FakeDatabase(existing_rows=[], insert_fails=True)
    auth = _FakeAuthService()
    service = _make_service(db, auth)
    user = _make_user(phone="+77787943760")

    # Must NOT raise — degraded mode is acceptable here
    result = await service.activate_free_trial(user)

    assert result.used_trial is True
    assert len(auth.activate_calls) == 1


@pytest.mark.asyncio
async def test_hash_is_recorded_after_auth_service_succeeds_not_before():
    """If we recorded the hash BEFORE auth_service, a Keycloak failure
    would leave the phone blacklisted forever without ever granting the
    trial — bad UX for the user. Order matters."""
    db = _FakeDatabase(existing_rows=[])
    auth = MagicMock()
    auth.activate_free_trial.side_effect = RuntimeError("simulated Keycloak failure")
    service = _make_service(db, auth)
    user = _make_user(phone="+77787943760")

    with pytest.raises(RuntimeError):
        await service.activate_free_trial(user)

    # No TrialHistory row was added — we short-circuited cleanly.
    assert all(not s.added for s in db._sessions)
