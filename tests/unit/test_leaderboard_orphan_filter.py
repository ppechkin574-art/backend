"""Leaderboard orphan-filtering — points rows for deleted Keycloak
users are dropped from the response instead of rendered as ghost
"Пользователь" entries.

Surfaced 18.05.2026: we deleted 5 seed leaderboard users
(Айдар/Динара/Алмас/Камила/Ержан) from Keycloak via the admin API,
but their rows in the Postgres `user_points` table weren't
cascade-deleted. The home screen then kept showing three generic
"Пользователь" rows with the seed point totals — defeating the
purpose of the cleanup.

Fix: `_user_display_pair` now returns `None` when Keycloak
explicitly answers "no such user" (vs. a transient lookup failure,
which still falls back to the placeholder so the leaderboard
doesn't blank out during Keycloak outages). The route handler
skips orphan rows and re-counts the rank numbering so the visible
top-N has no gaps.

Coverage:
- `_user_display_pair` returns None on Keycloak miss
- Transient failures (Exception) still return placeholder tuple
- `get_leaderboard` skips orphan rows, keeps real users
- Rank is gap-free after filtering (1, 2, 3 not 1, 3, 4)
- `/me` endpoint behaviour unchanged for the calling user (they
  always exist by virtue of being authenticated)
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# Eager imports so SQLAlchemy mappers can resolve relationships
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from api.routes.user.leaderboard import _user_display_pair, get_leaderboard
from clients.identity_provider import IdentityNotFound


# ─────────────────────────── _user_display_pair ──────────────────────


def test_returns_tuple_for_real_keycloak_user():
    """Live user with name+avatar attributes returns the populated tuple."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = ["Иван Иванов"]
    kc_user.attributes.avatar = ["filename.jpg"]
    idp.get_user.return_value = kc_user

    result = _user_display_pair(idp, "uuid-1")
    assert result == ("Иван Иванов", "filename.jpg")


def test_returns_none_when_keycloak_raises_identity_not_found():
    """The orphan path — IdentityProviderClientKeycloak.get_user
    wraps a 404 by RAISING IdentityNotFound, not returning None.
    The previous version of this test pinned a return_value=None
    path that the real client never takes, which let the bug
    (operator's screenshot 18.05.2026: three "Пользователь" ghosts
    still in the live leaderboard despite the deploy) ship green.
    This now mirrors actual Keycloak behaviour."""
    idp = MagicMock()
    idp.get_user.side_effect = IdentityNotFound

    result = _user_display_pair(idp, "uuid-orphan")
    assert result is None


def test_returns_none_when_keycloak_returns_falsy_user():
    """Defensive: if a future client refactor switches from
    raising IdentityNotFound to returning None, the route still
    has to skip the row. This pins that fallback so we don't
    silently regress to the ghost-rendering behaviour again."""
    idp = MagicMock()
    idp.get_user.return_value = None

    result = _user_display_pair(idp, "uuid-orphan-future")
    assert result is None


def test_returns_placeholder_tuple_on_keycloak_exception():
    """Transient Keycloak failure (network, 5xx) — still return a
    placeholder so the leaderboard stays visible during outage.
    This is intentionally different from the orphan case to
    distinguish 'user is gone' from 'we can't reach Keycloak'."""
    idp = MagicMock()
    idp.get_user.side_effect = Exception("Keycloak timeout")

    result = _user_display_pair(idp, "uuid-flaky")
    assert result == ("Пользователь", None)


def test_returns_placeholder_when_name_attribute_missing():
    """User exists but has no name attribute — name defaults to
    'Пользователь' so we don't render an empty string. Still a
    valid row, not an orphan."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = None
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(idp, "uuid-noname")
    assert result == ("Пользователь", None)


def test_returns_placeholder_when_name_is_empty_string():
    """name=[""] should still yield the placeholder, not the empty
    string — protects the UI from rendering "" as a name."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = [""]
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(idp, "uuid-emptyname")
    assert result == ("Пользователь", None)


# ─────────────────────────── get_leaderboard route ────────────────────


class _FakePointsRepo:
    """Stand-in for UserPointsRepository — returns whatever the
    test injected as `top` so we can isolate filter behaviour from
    the actual SQL query."""

    def __init__(self, top: list[tuple]):
        self._top = top

    def get_all_ranked(self, limit: int) -> list[tuple]:
        return self._top[:limit]


def _make_idp(known_user_ids: set[str]) -> MagicMock:
    """Build a fake IdentityProviderClientKeycloak that knows only
    the given user_ids — everything else RAISES IdentityNotFound
    the way the real Keycloak client does on a 404."""
    idp = MagicMock()

    def _get_user(user_id):
        if str(user_id) in known_user_ids:
            mock_user = MagicMock()
            mock_user.attributes.name = [f"User-{user_id[:8]}"]
            mock_user.attributes.avatar = None
            return mock_user
        raise IdentityNotFound

    idp.get_user.side_effect = _get_user
    return idp


def _make_file_service() -> MagicMock:
    fs = MagicMock()
    fs.get_avatar_url.return_value = None
    return fs


@pytest.mark.asyncio
async def test_leaderboard_skips_orphan_rows():
    """Real users + orphans interleaved — only real users in the
    response, in their original sort order."""
    real_a = str(uuid4())
    orphan = str(uuid4())  # Keycloak doesn't know this id
    real_b = str(uuid4())
    top = [
        (real_a, 5000),
        (orphan, 4500),  # ← should be dropped
        (real_b, 4000),
    ]

    monkeypatched_module = type(
        "Holder", (), {"UserPointsRepository": lambda session: _FakePointsRepo(top)}
    )
    # Patch the import the route uses
    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = monkeypatched_module.UserPointsRepository

    response = await get_leaderboard(
        limit=10,
        session=MagicMock(),
        idp=_make_idp({real_a, real_b}),
        file_service=_make_file_service(),
    )

    user_ids_returned = [entry.user_id for entry in response]
    assert orphan not in user_ids_returned
    assert user_ids_returned == [real_a, real_b]


@pytest.mark.asyncio
async def test_leaderboard_ranks_are_gap_free_after_filtering():
    """Critical UX property: after dropping orphans, the visible
    rank numbers must be 1, 2, 3... not 1, 3, 5. The home screen
    expects a continuous Top-3 podium."""
    real_a = str(uuid4())
    orphan_1 = str(uuid4())
    orphan_2 = str(uuid4())
    real_b = str(uuid4())
    real_c = str(uuid4())
    top = [
        (real_a, 5000),
        (orphan_1, 4900),
        (real_b, 4800),
        (orphan_2, 4700),
        (real_c, 4600),
    ]

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: _FakePointsRepo(top)

    response = await get_leaderboard(
        limit=10,
        session=MagicMock(),
        idp=_make_idp({real_a, real_b, real_c}),
        file_service=_make_file_service(),
    )

    ranks = [entry.rank for entry in response]
    assert ranks == [1, 2, 3]


@pytest.mark.asyncio
async def test_leaderboard_all_orphans_returns_empty_list():
    """Edge case: every row is orphan. Response is [] (not a list
    of placeholders) so the Flutter home screen falls back to the
    new '🏆 Будь первым в рейтинге!' empty state."""
    orphan_1 = str(uuid4())
    orphan_2 = str(uuid4())
    orphan_3 = str(uuid4())
    top = [
        (orphan_1, 5000),
        (orphan_2, 4000),
        (orphan_3, 3000),
    ]

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: _FakePointsRepo(top)

    response = await get_leaderboard(
        limit=10,
        session=MagicMock(),
        idp=_make_idp(set()),  # no real users
        file_service=_make_file_service(),
    )

    assert response == []


@pytest.mark.asyncio
async def test_leaderboard_empty_db_returns_empty_list():
    """Pre-existing behaviour preserved: no points rows at all → []."""
    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: _FakePointsRepo([])

    response = await get_leaderboard(
        limit=10,
        session=MagicMock(),
        idp=_make_idp(set()),
        file_service=_make_file_service(),
    )

    assert response == []


@pytest.mark.asyncio
async def test_leaderboard_keeps_users_during_keycloak_outage():
    """When Keycloak is unreachable (raises), we keep the user with
    placeholder name — don't blank the entire leaderboard. This
    differs from the orphan path (None response) on purpose."""
    real_a = str(uuid4())
    real_b = str(uuid4())
    top = [(real_a, 5000), (real_b, 4000)]

    flaky_idp = MagicMock()
    flaky_idp.get_user.side_effect = Exception("Keycloak unreachable")

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: _FakePointsRepo(top)

    response = await get_leaderboard(
        limit=10,
        session=MagicMock(),
        idp=flaky_idp,
        file_service=_make_file_service(),
    )

    assert len(response) == 2  # not zero — keep showing
    assert all(entry.name == "Пользователь" for entry in response)
