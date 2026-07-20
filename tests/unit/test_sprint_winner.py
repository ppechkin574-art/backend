"""CRM task #7 ("Еженедельный спринт" winner lock-in).

Covers:
- `LeaderboardPointsRepository.try_lock_sprint_winner` — concurrency
  safety. Two "racing" calls for the same week, different users: only
  the first lands, the second gets False even though both crossed the
  target. This mirrors the real `INSERT ... ON CONFLICT (week_start_at)
  DO NOTHING RETURNING user_id` semantics via a mocked `db.execute`
  that returns a row only on the first call.
- `LeaderboardPointsRepository.get_current_sprint_winner_row` — raw
  lookup used by the public endpoint.
- `LeaderboardPointsService.check_and_lock_sprint_winner` — the hook
  called from every points-award path. No-ops when the feature is off
  or the threshold isn't reached, respects the leaderboard hide-list,
  and NEVER raises (side-effect hook on the hot points-award path).
- `LeaderboardPointsService.get_sprint_status_raw` — the read path
  GET /leaderboard/sprint is built on.
- `GET /leaderboard/sprint` — response shape in all three states (not
  configured / configured no winner yet / configured with winner).
- `UserPointsRepository.add_points` — savepoint isolation. If the
  sprint-winner check's DB work raises INSIDE Postgres (not just a
  Python exception — an aborted transaction), the SAVEPOINT wrapping
  it must roll back so the outer transaction (and the points award
  that already happened in it) stays usable. A bare try/except is not
  sufficient for this — see `LeaderboardPointsService.
  check_and_lock_sprint_winner`'s docstring.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# Eager imports so SQLAlchemy mappers resolve relationships.
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from api.routes.user.leaderboard import SprintStatusEntry, get_sprint_status
from leaderboard_points.dtos import SprintWinnerDTO
from leaderboard_points.repository import LeaderboardPointsRepository
from leaderboard_points.service import LeaderboardPointsService
from quiz.repositories.user_points import UserPointsRepository
from security.models import PointsAuditLog

# ─── LeaderboardPointsRepository.try_lock_sprint_winner ─────────────────


class _FakeExecuteResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def test_try_lock_sprint_winner_first_call_wins():
    """Two calls for the SAME week, different users — only the first
    call's INSERT actually lands (simulates ON CONFLICT DO NOTHING);
    the second call must get False even though it also crosses the
    target."""
    db = MagicMock()
    calls = []

    def _execute(_stmt, params):
        calls.append(params)
        if len(calls) == 1:
            # First INSERT wins the UNIQUE constraint race — RETURNING
            # gives back its own user_id.
            return _FakeExecuteResult((params["user_id"],))
        # Second INSERT conflicts on week_start_at — DO NOTHING, no row.
        return _FakeExecuteResult(None)

    db.execute.side_effect = _execute
    repo = LeaderboardPointsRepository(db)

    week_start_at = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)
    user_a, user_b = uuid4(), uuid4()

    won_a = repo.try_lock_sprint_winner(week_start_at, user_a, 500)
    won_b = repo.try_lock_sprint_winner(week_start_at, user_b, 500)

    assert won_a is True
    assert won_b is False
    assert len(calls) == 2


def test_try_lock_sprint_winner_false_when_no_row_returned():
    """Straightforward conflict case — no row at all comes back."""
    db = MagicMock()
    db.execute.return_value = _FakeExecuteResult(None)
    repo = LeaderboardPointsRepository(db)

    result = repo.try_lock_sprint_winner(datetime(2026, 7, 20, tzinfo=UTC), uuid4(), 500)
    assert result is False


def test_try_lock_sprint_winner_false_when_returned_row_is_a_different_user():
    """Defensive case from the spec: a row comes back, but its user_id
    doesn't match the caller's — must still be False, never mistake
    someone else's win for your own."""
    db = MagicMock()
    caller_id = uuid4()
    someone_else_id = uuid4()
    db.execute.return_value = _FakeExecuteResult((someone_else_id,))
    repo = LeaderboardPointsRepository(db)

    result = repo.try_lock_sprint_winner(
        datetime(2026, 7, 20, tzinfo=UTC), caller_id, 500
    )
    assert result is False


# ─── LeaderboardPointsRepository.get_current_sprint_winner_row ──────────


def test_get_current_sprint_winner_row_returns_row_when_present():
    db = MagicMock()
    user_id = uuid4()
    won_at = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    db.query.return_value.filter.return_value.first.return_value = (user_id, 777, won_at)
    repo = LeaderboardPointsRepository(db)

    result = repo.get_current_sprint_winner_row(datetime(2026, 7, 19, 19, 0, tzinfo=UTC))
    assert result == (user_id, 777, won_at)


def test_get_current_sprint_winner_row_returns_none_when_absent():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    repo = LeaderboardPointsRepository(db)

    result = repo.get_current_sprint_winner_row(datetime(2026, 7, 19, 19, 0, tzinfo=UTC))
    assert result is None


# ─── LeaderboardPointsService.check_and_lock_sprint_winner ──────────────


def _fake_settings(**overrides):
    base = {
        "auto_reset_enabled": False,
        "reset_mode": "interval",
        "interval_days": 30,
        "last_reset_at": None,
        "sprint_target_points": None,
        "updated_at": datetime.now(UTC),
        "updated_by": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_service(settings, participants=None, weekly_points=None):
    """`participants` / `weekly_points` model the CRM #19 gates added on
    top of #7: only allowlisted users can win, and the threshold is
    compared against points earned THIS WEEK rather than the all-time
    total. Both default to empty, so a test that doesn't opt in exercises
    the "not a participant" short-circuit."""
    repo = MagicMock()
    repo.db = MagicMock()
    repo.get_or_create_settings.return_value = settings
    repo.participant_user_ids.return_value = participants or []
    repo.weekly_points.return_value = weekly_points or []
    return LeaderboardPointsService(repo=repo), repo


def _patch_hidden_list(monkeypatch, hidden_ids):
    """`check_and_lock_sprint_winner` lazily imports
    `LeaderboardHiddenRepository` inside its try block — patch the
    class in its home module so that lazy import picks up the fake."""
    import quiz.repositories.leaderboard_hidden as hidden_mod

    fake_repo = MagicMock()
    fake_repo.get_all.return_value = hidden_ids
    monkeypatch.setattr(hidden_mod, "LeaderboardHiddenRepository", lambda db: fake_repo)


def test_check_and_lock_noop_when_target_is_none(monkeypatch):
    settings = _fake_settings(sprint_target_points=None)
    service, repo = _make_service(settings)
    _patch_hidden_list(monkeypatch, [])

    service.check_and_lock_sprint_winner(uuid4(), 999)

    repo.try_lock_sprint_winner.assert_not_called()


def test_check_and_lock_noop_when_target_is_zero(monkeypatch):
    settings = _fake_settings(sprint_target_points=0)
    service, repo = _make_service(settings)
    _patch_hidden_list(monkeypatch, [])

    service.check_and_lock_sprint_winner(uuid4(), 999)

    repo.try_lock_sprint_winner.assert_not_called()


def test_check_and_lock_noop_when_below_target(monkeypatch):
    settings = _fake_settings(sprint_target_points=1000)
    service, repo = _make_service(settings)
    _patch_hidden_list(monkeypatch, [])

    service.check_and_lock_sprint_winner(uuid4(), 999)

    repo.try_lock_sprint_winner.assert_not_called()


def test_check_and_lock_locks_when_target_reached(monkeypatch):
    settings = _fake_settings(sprint_target_points=1000)
    user_id = uuid4()
    # Allowlisted (CRM #19) and 1000 of their points were earned this week.
    service, repo = _make_service(
        settings,
        participants=[user_id],
        weekly_points=[(user_id, 1000, datetime.now(UTC))],
    )
    _patch_hidden_list(monkeypatch, [])

    service.check_and_lock_sprint_winner(user_id, 1000)

    repo.try_lock_sprint_winner.assert_called_once()
    call_args = repo.try_lock_sprint_winner.call_args[0]
    assert call_args[1] == user_id
    assert call_args[2] == 1000


def test_check_and_lock_skips_hidden_users(monkeypatch):
    """Same exclusion the public leaderboard already applies to hidden
    users — they shouldn't be able to headline the sprint banner
    either, even if they numerically cross the target."""
    settings = _fake_settings(sprint_target_points=1000)
    user_id = uuid4()
    # Allowlisted and above the weekly target — so the ONLY thing that can
    # stop the lock here is the hide-list, which is what this asserts.
    service, repo = _make_service(
        settings,
        participants=[user_id],
        weekly_points=[(user_id, 1500, datetime.now(UTC))],
    )
    _patch_hidden_list(monkeypatch, [str(user_id)])

    service.check_and_lock_sprint_winner(user_id, 1500)

    repo.try_lock_sprint_winner.assert_not_called()


def test_check_and_lock_never_raises_on_repo_failure(monkeypatch):
    """Hard requirement: this runs inline in the hot points-award path
    (ЕНТ/battle/referral) — a bug here must never break the caller's
    actual points award."""
    settings = _fake_settings(sprint_target_points=1000)
    user_id = uuid4()
    # Must actually REACH try_lock_sprint_winner for its failure to be the
    # thing under test — hence allowlisted and over the weekly target.
    service, repo = _make_service(
        settings,
        participants=[user_id],
        weekly_points=[(user_id, 2000, datetime.now(UTC))],
    )
    repo.try_lock_sprint_winner.side_effect = RuntimeError("boom")
    _patch_hidden_list(monkeypatch, [])

    # Must not raise.
    service.check_and_lock_sprint_winner(user_id, 2000)
    repo.try_lock_sprint_winner.assert_called_once()


def test_check_and_lock_never_raises_when_settings_lookup_fails():
    repo = MagicMock()
    repo.db = MagicMock()
    repo.get_or_create_settings.side_effect = RuntimeError("db down")
    service = LeaderboardPointsService(repo=repo)

    # Must not raise.
    service.check_and_lock_sprint_winner(uuid4(), 2000)


# ─── LeaderboardPointsService.get_sprint_status_raw ──────────────────────


def test_get_sprint_status_raw_feature_off():
    settings = _fake_settings(sprint_target_points=None)
    service, repo = _make_service(settings)

    target, week_start_at, winner_row = service.get_sprint_status_raw()

    assert target is None
    assert week_start_at is None
    assert winner_row is None
    repo.get_current_sprint_winner_row.assert_not_called()


def test_get_sprint_status_raw_configured_no_winner():
    settings = _fake_settings(sprint_target_points=1000)
    service, repo = _make_service(settings)
    repo.get_current_sprint_winner_row.return_value = None

    target, week_start_at, winner_row = service.get_sprint_status_raw()

    assert target == 1000
    assert week_start_at is not None
    assert winner_row is None


def test_get_sprint_status_raw_configured_with_winner():
    settings = _fake_settings(sprint_target_points=1000)
    service, repo = _make_service(settings)
    user_id = uuid4()
    won_at = datetime.now(UTC)
    repo.get_current_sprint_winner_row.return_value = (user_id, 1200, won_at)

    target, week_start_at, winner_row = service.get_sprint_status_raw()

    assert target == 1000
    assert week_start_at is not None
    assert winner_row == (user_id, 1200, won_at)


# ─── GET /leaderboard/sprint ─────────────────────────────────────────────


def _make_idp_for(user_id: str, name: str = "Чемпион"):
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = [name]
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user
    return idp


class _FakeDisplayRepo:
    def __init__(self, *_a, **_k):
        pass

    def bulk_get(self, _ids):
        return {}

    def upsert(self, *_a, **_k):
        pass


@pytest.fixture(autouse=True)
def _patch_user_display(monkeypatch):
    import api.routes.user.leaderboard as lb

    monkeypatch.setattr(lb, "UserDisplayRepository", lambda session: _FakeDisplayRepo())


def _make_cache():
    cache = MagicMock()
    cache.get.return_value = None
    return cache


def _make_file_service():
    fs = MagicMock()
    fs.get_avatar_url.return_value = None
    return fs


class _FakeSprintService:
    def __init__(self, target, week_start_at, winner_row):
        self._result = (target, week_start_at, winner_row)

    def get_sprint_status_raw(self):
        return self._result


@pytest.mark.asyncio
async def test_endpoint_not_configured_returns_all_null():
    service = _FakeSprintService(None, None, None)

    response = await get_sprint_status(
        session=MagicMock(),
        idp=MagicMock(),
        file_service=_make_file_service(),
        cache=_make_cache(),
        lb_points_service=service,
    )

    assert response == SprintStatusEntry(target_points=None, week_start_at=None, winner=None)


@pytest.mark.asyncio
async def test_endpoint_configured_no_winner_yet():
    week_start_at = datetime(2026, 7, 19, 19, 0, tzinfo=UTC)
    service = _FakeSprintService(1000, week_start_at, None)

    response = await get_sprint_status(
        session=MagicMock(),
        idp=MagicMock(),
        file_service=_make_file_service(),
        cache=_make_cache(),
        lb_points_service=service,
    )

    assert response.target_points == 1000
    assert response.week_start_at == week_start_at
    assert response.winner is None


@pytest.mark.asyncio
async def test_endpoint_configured_with_winner_resolves_display():
    week_start_at = datetime(2026, 7, 19, 19, 0, tzinfo=UTC)
    won_at = datetime(2026, 7, 20, 8, 30, tzinfo=UTC)
    user_id = uuid4()
    service = _FakeSprintService(1000, week_start_at, (user_id, 1200, won_at))

    response = await get_sprint_status(
        session=MagicMock(),
        idp=_make_idp_for(str(user_id), name="Чемпион недели"),
        file_service=_make_file_service(),
        cache=_make_cache(),
        lb_points_service=service,
    )

    assert response.target_points == 1000
    assert response.week_start_at == week_start_at
    assert response.winner == SprintWinnerDTO(
        user_id=str(user_id),
        name="Чемпион недели",
        avatar_url=None,
        points_at_win=1200,
        won_at=won_at,
    )


# ─── UserPointsRepository.add_points — savepoint isolation ──────────────
#
# A bare Python try/except around the sprint-winner check is NOT enough:
# if the check's SQL raises inside Postgres (e.g. `sprint_winners` doesn't
# exist yet during a deploy window where the backend ships before the
# Alembic migration runs — Railway auto-deploy doesn't order the two),
# Postgres aborts the WHOLE transaction. Catching the Python exception
# doesn't un-abort it — the caller's later `session.commit()` (e.g.
# `EntAttemptService.answer()`'s `self._uow.commit()`) would then raise,
# unhandled, breaking exam completion for the user. `check_and_lock_
# sprint_winner` wraps its DB work in `db.begin_nested()` (a SAVEPOINT)
# for exactly this reason — see its docstring.
#
# `unittest.mock.MagicMock` can't model this: it never raises on its own
# and has no notion of "the connection is now unusable until rolled
# back." `_FakeSession` below is a minimal double that DOES model that —
# `aborted=True` makes every subsequent DB call raise (mirrors Postgres
# rejecting all commands until `ROLLBACK`/`ROLLBACK TO SAVEPOINT`), and
# `begin_nested()`'s context manager clears the flag on exception exit
# (mirrors `ROLLBACK TO SAVEPOINT` — the outer transaction recovers).
# This proves the SAVEPOINT is actually doing its job, not just that no
# exception happens to propagate out of `add_points()`.


class _FakeNestedTxn:
    """Models the one property of `Session.begin_nested()` this test
    cares about: on a clean exit it does nothing special; on an
    exception it "issues ROLLBACK TO SAVEPOINT" (clears `aborted`) and
    then re-raises — it never swallows."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._session.rolled_back_to_savepoint = True
            self._session.aborted = False
        return False


class _FakeSession:
    """Minimal Session double with just enough Postgres-transaction
    semantics to prove savepoint isolation — not a general-purpose
    session mock."""

    def __init__(self):
        self.aborted = False
        self.rolled_back_to_savepoint = False
        self.committed = False
        self.added: list = []
        self.executed: list = []

    def _guard(self):
        if self.aborted:
            raise Exception(
                "current transaction is aborted, commands ignored until "
                "end of transaction block"
            )

    def execute(self, stmt, params=None):
        self._guard()
        self.executed.append((stmt, params))
        result = MagicMock()
        result.scalar.return_value = 500
        result.first.return_value = None
        return result

    def add(self, obj):
        self._guard()
        self.added.append(obj)

    def query(self, *_a, **_k):
        self._guard()
        m = MagicMock()
        m.filter.return_value.first.return_value = None
        m.order_by.return_value.first.return_value = None
        # `add_points` looks up UserRiskProfile.points_frozen before awarding.
        # No risk profile row → NULL → not frozen, which is the case for
        # virtually every user and the one this test cares about.
        m.filter.return_value.scalar.return_value = None
        return m

    def begin_nested(self):
        return _FakeNestedTxn(self)

    def commit(self):
        self._guard()
        self.committed = True


def test_add_points_survives_sprint_check_aborting_the_transaction(monkeypatch):
    """Simulates the deploy-race failure mode: the sprint-winner check's
    first DB call (`get_or_create_settings`) blows up as if
    `sprint_target_points`/`sprint_winners` don't exist yet, aborting
    the Postgres transaction. Asserts:

    1. `add_points()` itself doesn't raise (the baseline "never breaks
       the caller" requirement).
    2. The points award that already happened (UPSERT + audit log) is
       untouched — it ran BEFORE the sprint check and isn't rolled back
       by the savepoint (the savepoint only covers the sprint-check's
       own work).
    3. The SAVEPOINT actually engaged (`rolled_back_to_savepoint`),
       proving the transaction was un-aborted — not just that the
       Python exception didn't propagate.
    4. The caller's subsequent `commit()` (mirrors `self._uow.commit()`
       right after `add_points()` in `ent_attempts.py`) succeeds — this
       is what would have raised, unhandled, without the savepoint.
    """
    session = _FakeSession()
    repo = UserPointsRepository(session)
    user_id = uuid4()

    def _boom(self):
        # Simulate a real Postgres error (missing column/table) — the
        # connection is now aborted until rolled back, exactly like the
        # real DBAPI/psycopg2 behaviour this is standing in for.
        session.aborted = True
        raise Exception('relation "sprint_winners" does not exist')

    monkeypatch.setattr(LeaderboardPointsRepository, "get_or_create_settings", _boom)

    # Must not raise.
    repo.add_points(user_id, 500, source_type="ent_attempt", source_id="attempt-1")

    # The points award itself completed before the sprint check ran.
    assert len(session.executed) == 1  # the total_points UPSERT
    assert len(session.added) == 1
    assert isinstance(session.added[0], PointsAuditLog)
    assert session.added[0].points_delta == 500

    # The savepoint actually rolled back the abort...
    assert session.rolled_back_to_savepoint is True
    assert session.aborted is False

    # ...so the caller's subsequent commit() (which would otherwise
    # raise on an aborted transaction) succeeds.
    session.commit()
    assert session.committed is True


def test_add_points_without_savepoint_would_have_left_transaction_aborted():
    """Control case, not exercising production code: proves `_FakeSession`
    itself faithfully models "no rollback → still aborted → commit
    raises", so the green result of the test above is actually meaningful
    (i.e. it's the savepoint doing the work, not a lenient fake)."""
    session = _FakeSession()
    session.aborted = True  # no ROLLBACK TO SAVEPOINT ever issued

    with pytest.raises(Exception, match="aborted"):
        session.commit()
