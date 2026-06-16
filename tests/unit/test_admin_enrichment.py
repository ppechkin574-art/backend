"""Regression test for _enrich_with_pg_stats silent failure.

Bug: ANY(:ids) with a Python list in SQLAlchemy text() fails silently when
psycopg2 can't adapt the list to a PostgreSQL array (type mismatch between
text[] and uuid column). The except block swallowed the error, causing all
streak/points to remain at the DTO default (0) → displayed as "—" in admin.

Fix: use IN :ids with bindparam("ids", expanding=True) + cast to ::text,
so SQLAlchemy expands the list to individual params and the cast makes the
type match explicit.
"""

from unittest.mock import MagicMock, call, patch
from uuid import UUID

from auth.admin_service import AdminUserService
from auth.dtos.users import UserDTO
from common.enums import PlanType


def _user(uid: str) -> UserDTO:
    return UserDTO(
        id=UUID(uid),
        username=f"user_{uid[:8]}",
        name="Test",
        is_active=True,
        plan=PlanType.FREE,
        roles=[],
    )


def _make_svc(session: MagicMock) -> AdminUserService:
    svc = AdminUserService.__new__(AdminUserService)
    svc._session = session
    return svc


def test_enrich_sets_streak_and_points_from_pg():
    """When PG returns rows, attendance_streak_days and points must be set."""
    uid1 = "11111111-1111-1111-1111-111111111111"
    uid2 = "22222222-2222-2222-2222-222222222222"
    users = [_user(uid1), _user(uid2)]

    session = MagicMock()

    # First execute → streak rows, second → points rows
    streak_result = MagicMock()
    streak_result.fetchall.return_value = [
        (uid1, 7, 350),
        (uid2, 3, 120),
    ]
    points_result = MagicMock()
    points_result.fetchall.return_value = [
        (uid1, 1000),
        (uid2, 500),
    ]
    session.execute.side_effect = [streak_result, points_result]

    svc = _make_svc(session)
    svc._enrich_with_pg_stats(users)

    assert users[0].attendance_streak_days == 7
    assert users[0].attendance_total_points == 350
    assert users[0].points == 1000

    assert users[1].attendance_streak_days == 3
    assert users[1].attendance_total_points == 120
    assert users[1].points == 500


def test_enrich_defaults_when_no_pg_rows():
    """Users not in attendance_streaks or students keep DTO defaults (0)."""
    uid1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    users = [_user(uid1)]

    session = MagicMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    session.execute.return_value = empty

    svc = _make_svc(session)
    svc._enrich_with_pg_stats(users)

    assert users[0].attendance_streak_days == 0
    assert users[0].points == 0


def test_enrich_uses_two_execute_calls():
    """Must make exactly 2 DB calls — one for streaks, one for points."""
    uid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    users = [_user(uid)]

    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result

    svc = _make_svc(session)
    svc._enrich_with_pg_stats(users)

    assert session.execute.call_count == 2


def test_enrich_handles_pg_exception_gracefully():
    """If DB throws, _enrich_with_pg_stats must not propagate — users stay at defaults."""
    uid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    users = [_user(uid)]

    session = MagicMock()
    session.execute.side_effect = Exception("DB is down")

    svc = _make_svc(session)
    svc._enrich_with_pg_stats(users)  # must not raise

    assert users[0].attendance_streak_days == 0
    assert users[0].points == 0
