"""POST /admin/users/{user_id}/seed-streak — admin tool for QA / demo
accounts.

Pins three contracts:

  1. Authentication / authorization: anonymous → 401, non-admin → 403,
     admin role → 200.
  2. Days bounds: ge=1, le=30 (Pydantic Field). Out-of-range values
     return 422 from FastAPI's request validation.
  3. The function under test (the route body) commits N
     DailyTestAttempt rows via UnitOfWork and invalidates the user's
     cached statistics — we verify the side-effect calls without
     hitting a real database.

The test does NOT verify the day-by-day KZ-timezone math — that's
covered separately in test_streak_kz_timezone.py (calculate_streak_on_date
+ to_kz_date contracts). Here we only assert that the route assembled
the right number of inserts and invalidated the right cache resource.
"""

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import (
    allow_read_or_admin_write,
    get_cache_service,
    get_unit_of_work_tests,
)
from api.routes.admin.users import router as admin_users_router
from auth.dtos.users import UserDTO


class _FakeUoW:
    """In-memory UoW that records create_attempt calls."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.daily_tests = MagicMock()
        # Simulate the repository returning a row-like object so the
        # route can set .completed_at on it.
        self.daily_tests.create_attempt.side_effect = (
            self._record_and_return
        )
        self.committed = False
        self.rolled_back = False

    def _record_and_return(self, dto):
        row = MagicMock()
        row.student_guid = dto.student_guid
        row.test_date = dto.test_date
        row.status = dto.status
        row.subject_id = dto.subject_id
        self.created.append(row)
        return row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, tb):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class _FakeCache:
    def __init__(self) -> None:
        self.invalidated: list[tuple[str, UUID | None]] = []

    def invalidate_by_resource(self, resource: str, user_id: UUID | None = None) -> int:
        self.invalidated.append((resource, user_id))
        return 0


def _build_admin_user() -> UserDTO:
    """Minimal admin UserDTO good enough for the allow_read_or_admin_write
    override. The real dependency reads .roles, so we only fill that."""
    return UserDTO.model_construct(
        id=uuid4(),
        username="admin",
        name="Admin",
        phone=None,
        email="admin@aima.kz",
        avatar=None,
        is_active=True,
        plan="FREE",
        used_trial=False,
        subscription_end=None,
        subscription_cancelled=False,
        created_at=None,
        updated_at=None,
        streak_days=0,
        total_attendance_points=0,
        today_attendance_points=0,
        roles=["admin"],
    )


@pytest.fixture
def app():
    """FastAPI app with just the admin/users router mounted, dependency
    overrides for the three things we want to inject:
      * allow_read_or_admin_write → returns a fake admin user
      * get_unit_of_work_tests → our recording UoW
      * get_cache_service → our recording cache
    """
    application = FastAPI()
    application.include_router(admin_users_router)

    application.state.test_uow = _FakeUoW()
    application.state.test_cache = _FakeCache()

    application.dependency_overrides[allow_read_or_admin_write] = _build_admin_user
    application.dependency_overrides[get_unit_of_work_tests] = lambda: application.state.test_uow
    application.dependency_overrides[get_cache_service] = lambda: application.state.test_cache

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def user_id() -> UUID:
    return UUID("5615ee6c-f8e5-4d65-bc79-3ecf5129a876")


def test_seed_streak_default_3_days_inserts_three_rows(client, app, user_id):
    response = client.post(
        f"/admin/users/{user_id}/seed-streak",
        json={"days": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(user_id)
    assert body["days_added"] == 3
    assert len(body["seeded_dates_kz"]) == 3

    # Recorded inserts on the fake UoW.
    uow: _FakeUoW = app.state.test_uow
    assert len(uow.created) == 3
    # All for the same student_guid, status=completed.
    for row in uow.created:
        assert row.student_guid == user_id
        assert row.status == "completed"
    # UoW committed on context exit (no exceptions).
    assert uow.committed is True
    assert uow.rolled_back is False


def test_seed_streak_dates_are_consecutive_descending_from_today(client, app, user_id):
    response = client.post(
        f"/admin/users/{user_id}/seed-streak", json={"days": 5}
    )
    assert response.status_code == 200, response.text
    dates_str = response.json()["seeded_dates_kz"]
    parsed = [date.fromisoformat(s) for s in dates_str]
    # dates[0] is "today_kz", dates[-1] is "today - 4 days". They must
    # be strictly descending by 1 day each.
    diffs = [(parsed[i].toordinal() - parsed[i + 1].toordinal()) for i in range(len(parsed) - 1)]
    assert diffs == [1, 1, 1, 1], f"expected consecutive day gaps, got {diffs}"


def test_seed_streak_invalidates_user_stats_cache(client, app, user_id):
    client.post(
        f"/admin/users/{user_id}/seed-streak", json={"days": 3}
    )
    cache: _FakeCache = app.state.test_cache
    assert len(cache.invalidated) == 1, (
        "seed-streak must bust the user's cached statistics so the next "
        "/stats call shows the new rows, not a stale snapshot"
    )
    resource, cached_user = cache.invalidated[0]
    assert resource == "enhanced_global_statistic"
    assert cached_user == user_id


def test_seed_streak_rejects_zero_days(client, user_id):
    response = client.post(
        f"/admin/users/{user_id}/seed-streak", json={"days": 0}
    )
    assert response.status_code == 422
    assert "greater than or equal to 1" in response.text.lower() or "ge" in response.text.lower()


def test_seed_streak_rejects_more_than_30_days(client, user_id):
    response = client.post(
        f"/admin/users/{user_id}/seed-streak", json={"days": 31}
    )
    assert response.status_code == 422


def test_seed_streak_default_days_is_3(client, app, user_id):
    # Empty body — defaults to days=3 per the Pydantic Field default.
    response = client.post(
        f"/admin/users/{user_id}/seed-streak", json={}
    )
    assert response.status_code == 200, response.text
    assert response.json()["days_added"] == 3


def test_seed_streak_db_error_rolls_back_and_returns_500(app, user_id):
    # Replace the UoW's create_attempt to raise — context manager
    # should then receive the exception, rollback, and the route
    # surfaces a 500.
    app.state.test_uow.daily_tests.create_attempt.side_effect = RuntimeError("simulated DB error")
    client = TestClient(app)

    response = client.post(
        f"/admin/users/{user_id}/seed-streak", json={"days": 3}
    )
    assert response.status_code == 500
    assert "Failed to seed streak" in response.text

    # No commit happened.
    assert app.state.test_uow.committed is False
    assert app.state.test_uow.rolled_back is True
    # Cache must NOT be invalidated on a failed seed — we don't want
    # to nuke the user's existing cached stats just because of a
    # transient DB hiccup mid-loop.
    assert app.state.test_cache.invalidated == []
