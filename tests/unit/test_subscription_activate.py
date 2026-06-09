"""Subscription activation — external `expires_at` overrides stacking.

Covers `SubscriptionService.activate_subscription` after the
restore-purchases bug fix (16.05.2026). Two modes:

  - **external** — caller supplies `expires_at` from a trusted source
    (Apple receipt, App Store Server Notification). We use it as-is,
    no stacking. This is the path that fixes the "restore on already-
    active PRO inflates time" bug.

  - **computed** — no `expires_at`, we add `plan.duration_days * months`
    to either user's existing `subscription_end` (stacking, when user
    is already PRO) or `now()` (fresh). This is the legacy path used
    by FreedomPay webhook where amount paid implies duration.

Coverage matrix:
- expires_at provided + user FREE → uses expires_at directly
- expires_at provided + user already active PRO → uses expires_at,
  does NOT stack on top of existing subscription_end
- expires_at NOT provided + user FREE → now + 30 days (fresh)
- expires_at NOT provided + user active PRO → user.subscription_end
  + 30 days (legacy stacking behaviour preserved for FreedomPay)
- expires_at NOT provided + user has expired PRO → now + 30 days
  (treat as fresh, don't extend from past expiry)
- plan = FREE → subscription_end set to None regardless of expires_at
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# SQLAlchemy mapper resolution
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from auth.dtos.users import UserDTO
from common.enums import PlanType
from subscription.service import SubscriptionService


class _FakeAuthService:
    """Captures update_user_profile call so tests can inspect the DTO."""

    def __init__(self):
        self.calls: list[tuple] = []

    def update_user_profile(self, user, update_data):
        self.calls.append((user, update_data))
        return user.model_copy(
            update={
                "plan": update_data.plan if update_data.plan is not None else user.plan,
                "subscription_end": update_data.subscription_end,
            }
        )


class _FakeDatabase:
    """SubscriptionService needs a Database for get_plan_features cache;
    we don't exercise the DB path here — service falls through to
    `_get_default_plan_features` which has PRO with duration_days=30."""

    class _Session:
        def query(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def all(self):
            return []

        def first(self):
            return None

        def close(self):
            pass

    @property
    def session(self):
        return self._Session()


def _make_user(*, plan: PlanType = PlanType.FREE, subscription_end: datetime | None = None) -> UserDTO:
    return UserDTO(
        id=uuid4(),
        username="test-user",
        name="Test User",
        email="test@example.com",
        phone="+77001234567",
        plan=plan,
        subscription_end=subscription_end,
        used_trial=False,
        is_active=True,
    )


def _make_service() -> tuple[SubscriptionService, _FakeAuthService]:
    auth = _FakeAuthService()
    svc = SubscriptionService(auth_service=auth, database=_FakeDatabase())
    return svc, auth


# ─────────────────────────── External expires_at — primary fix ───────────────────────────


@pytest.mark.asyncio
async def test_external_expires_at_used_for_free_user():
    """Fresh user receiving Apple receipt with explicit expiry: we
    write Apple's date, not now+30."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.FREE)
    apple_expiry = datetime.now(UTC) + timedelta(days=29, hours=23)  # ~30 days, Apple's exact date

    await svc.activate_subscription(user, PlanType.PRO, expires_at=apple_expiry)

    _, dto = auth.calls[0]
    assert dto.plan == PlanType.PRO
    assert dto.subscription_end == apple_expiry


@pytest.mark.asyncio
async def test_external_expires_at_does_not_stack_on_active_pro():
    """THE BUG FIX: restore-purchases on already-PRO user must NOT add
    30 days on top of remaining time. We've seen this produce 59 days
    in testing — the second activation stacked. With explicit
    expires_at from Apple, we use exactly what Apple says."""
    svc, auth = _make_service()
    existing_end = datetime.now(UTC) + timedelta(days=29)  # user has 29 days left
    user = _make_user(plan=PlanType.PRO, subscription_end=existing_end)
    apple_expiry = datetime.now(UTC) + timedelta(days=30)  # Apple says 30 days from now

    await svc.activate_subscription(user, PlanType.PRO, expires_at=apple_expiry)

    _, dto = auth.calls[0]
    # We use Apple's date directly, not existing_end + 30 days (which
    # would be ~59 days). No stacking.
    assert dto.subscription_end == apple_expiry
    # Sanity: result is nowhere near "stacked" 59-day value
    delta = (dto.subscription_end - datetime.now(UTC)).days
    assert delta < 35, f"expected ~30 days, got {delta}"


@pytest.mark.asyncio
async def test_external_expires_at_overrides_months_param():
    """If caller passes BOTH `months` and `expires_at`, the external
    date wins. Defensive: catches a future caller who accidentally
    passes both."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.FREE)
    apple_expiry = datetime(2026, 12, 31, tzinfo=UTC)

    await svc.activate_subscription(user, PlanType.PRO, months=12, expires_at=apple_expiry)

    _, dto = auth.calls[0]
    assert dto.subscription_end == apple_expiry  # not now + 12*30 days


# ─────────────────────────── Legacy computed path — FreedomPay preservation ───────────────────────────


@pytest.mark.asyncio
async def test_computed_path_free_user_gets_30_days_from_now():
    """Legacy path (no expires_at) on a FREE user — fresh 30 days."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.FREE)
    before = datetime.now(UTC)

    await svc.activate_subscription(user, PlanType.PRO, months=1)

    after = datetime.now(UTC)
    _, dto = auth.calls[0]
    # 30 days from "now", with some tolerance
    expected_min = before + timedelta(days=30) - timedelta(seconds=2)
    expected_max = after + timedelta(days=30) + timedelta(seconds=2)
    assert expected_min <= dto.subscription_end <= expected_max


@pytest.mark.asyncio
async def test_computed_path_active_pro_stacks_legacy_behavior():
    """Legacy stacking preserved — FreedomPay can still call this way
    when a user pays for a second month while the first is still
    active. The 30 new days land on top of remaining time."""
    svc, auth = _make_service()
    existing_end = datetime.now(UTC) + timedelta(days=20)
    user = _make_user(plan=PlanType.PRO, subscription_end=existing_end)

    await svc.activate_subscription(user, PlanType.PRO, months=1)

    _, dto = auth.calls[0]
    expected = existing_end + timedelta(days=30)
    assert abs((dto.subscription_end - expected).total_seconds()) < 2


@pytest.mark.asyncio
async def test_computed_path_expired_pro_starts_fresh_from_now():
    """User WAS PRO but subscription_end is in the past — treat as
    FREE for the start_date calculation. Don't extend a past date."""
    svc, auth = _make_service()
    past_end = datetime.now(UTC) - timedelta(days=5)
    user = _make_user(plan=PlanType.PRO, subscription_end=past_end)
    before = datetime.now(UTC)

    await svc.activate_subscription(user, PlanType.PRO, months=1)

    _, dto = auth.calls[0]
    # New end is ~30 days from NOW, not (past_end + 30 days).
    assert dto.subscription_end > before + timedelta(days=29)
    assert dto.subscription_end < before + timedelta(days=31)


@pytest.mark.asyncio
async def test_computed_path_multiple_months():
    """months=3 → fresh user gets 90 days."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.FREE)
    before = datetime.now(UTC)

    await svc.activate_subscription(user, PlanType.PRO, months=3)

    _, dto = auth.calls[0]
    delta = (dto.subscription_end - before).days
    assert 89 <= delta <= 90


# ─────────────────────────── Downgrade-to-FREE path ───────────────────────────


@pytest.mark.asyncio
async def test_downgrade_to_free_clears_subscription_end():
    """Activating FREE explicitly clears subscription_end regardless
    of whether expires_at was passed."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=30))

    await svc.activate_subscription(user, PlanType.FREE)

    _, dto = auth.calls[0]
    assert dto.plan == PlanType.FREE
    assert dto.subscription_end is None


@pytest.mark.asyncio
async def test_downgrade_to_free_ignores_expires_at():
    """Even if a caller mistakenly passes expires_at while downgrading,
    we still clear subscription_end. FREE has no end date."""
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.PRO, subscription_end=datetime.now(UTC) + timedelta(days=30))

    await svc.activate_subscription(
        user, PlanType.FREE, expires_at=datetime.now(UTC) + timedelta(days=999)
    )

    _, dto = auth.calls[0]
    assert dto.subscription_end is None


# ─────────────────────────── Error path ───────────────────────────


@pytest.mark.asyncio
async def test_auth_service_failure_propagates_as_500():
    """If Keycloak update fails, we wrap as HTTP 500 — same as the
    pre-fix behaviour. Confirms we didn't accidentally swallow errors."""
    from fastapi import HTTPException

    svc, _ = _make_service()
    # Make _FakeAuthService raise
    svc.auth_service = MagicMock()
    svc.auth_service.update_user_profile.side_effect = RuntimeError("Keycloak down")
    user = _make_user(plan=PlanType.FREE)

    with pytest.raises(HTTPException) as exc:
        await svc.activate_subscription(
            user, PlanType.PRO, expires_at=datetime.now(UTC) + timedelta(days=30)
        )

    assert exc.value.status_code == 500


# ─────────────────────────── revoke_subscription (#3 — refund/REVOKED) ───────────────────────────


def test_revoke_downgrades_active_pro_to_free():
    svc, auth = _make_service()
    user = _make_user(
        plan=PlanType.PRO,
        subscription_end=datetime.now(UTC) + timedelta(days=20),
    )

    updated = svc.revoke_subscription(user)

    assert len(auth.calls) == 1
    _, update_data = auth.calls[0]
    assert update_data.plan == PlanType.FREE
    assert update_data.subscription_end is None
    assert updated.plan == PlanType.FREE


def test_revoke_is_noop_for_free_user():
    svc, auth = _make_service()
    user = _make_user(plan=PlanType.FREE)

    updated = svc.revoke_subscription(user)

    assert auth.calls == []  # nothing to revoke
    assert updated.plan == PlanType.FREE
