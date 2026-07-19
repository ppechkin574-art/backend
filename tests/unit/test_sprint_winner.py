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


def _make_service(settings):
    repo = MagicMock()
    repo.db = MagicMock()
    repo.get_or_create_settings.return_value = settings
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
    service, repo = _make_service(settings)
    _patch_hidden_list(monkeypatch, [])
    user_id = uuid4()

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
    service, repo = _make_service(settings)
    user_id = uuid4()
    _patch_hidden_list(monkeypatch, [str(user_id)])

    service.check_and_lock_sprint_winner(user_id, 1500)

    repo.try_lock_sprint_winner.assert_not_called()


def test_check_and_lock_never_raises_on_repo_failure(monkeypatch):
    """Hard requirement: this runs inline in the hot points-award path
    (ЕНТ/battle/referral) — a bug here must never break the caller's
    actual points award."""
    settings = _fake_settings(sprint_target_points=1000)
    service, repo = _make_service(settings)
    repo.try_lock_sprint_winner.side_effect = RuntimeError("boom")
    _patch_hidden_list(monkeypatch, [])

    # Must not raise.
    service.check_and_lock_sprint_winner(uuid4(), 2000)


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
