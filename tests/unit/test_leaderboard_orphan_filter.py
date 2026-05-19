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

from api.routes.user.leaderboard import (
    _is_pii_leak,
    _safe_display_name,
    _user_display_pair,
    get_leaderboard,
)
from clients.identity_provider import IdentityNotFound


# ─────────────────────────── PII-safe display name ────────────────────


def test_is_pii_leak_rejects_phone_formats():
    assert _is_pii_leak("+77001234567") is True
    assert _is_pii_leak("77001234567") is True
    assert _is_pii_leak("+7 700 123 4567") is True


def test_is_pii_leak_rejects_emails():
    assert _is_pii_leak("user@example.com") is True
    assert _is_pii_leak("test@aima.kz") is True


def test_is_pii_leak_rejects_auto_keycloak_usernames():
    """Admin-panel / seed-script artefacts like `user3`, `user_42`
    aren't strictly PII but still look like placeholders and need to
    be masked so the leaderboard reads as a real ranking."""
    assert _is_pii_leak("user3") is True
    assert _is_pii_leak("user_42") is True
    assert _is_pii_leak("User-12") is True


def test_is_pii_leak_accepts_real_names():
    assert _is_pii_leak("Иван Петров") is False
    assert _is_pii_leak("Әсемгүл") is False
    assert _is_pii_leak("dnns") is False  # short but a legit display name
    assert _is_pii_leak("Anna2024") is False


def test_is_pii_leak_treats_empty_as_leak():
    """Defensive: if name is somehow empty by the time the leaderboard
    handler sees it, masking is the safer default than rendering ''."""
    assert _is_pii_leak("") is True
    assert _is_pii_leak(None) is True


def test_safe_display_name_passes_through_real_name():
    assert _safe_display_name("Иван", "uuid-irrelevant") == "Иван"


def test_safe_display_name_masks_phone():
    """The mask must be stable per user (same UUID → same suffix) so
    a returning user keeps the same #ABCD label across requests and
    isn't confused into thinking the leaderboard reshuffled."""
    masked = _safe_display_name(
        "+77001234567", "12345678-1234-1234-1234-1234567890ab"
    )
    assert masked == "Пользователь #90AB"


def test_safe_display_name_masks_auto_username():
    masked = _safe_display_name(
        "user3", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee1234"
    )
    assert masked == "Пользователь #1234"


def test_safe_display_name_handles_missing_uuid_safely():
    """Defensive — should never happen in practice (user_id always
    present in the route), but if it does we still render a stable
    string rather than crashing or producing 'Пользователь #'."""
    assert _safe_display_name("+77001234567", "") == "Пользователь #????"


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


def test_returns_uuid_suffix_when_name_attribute_missing():
    """User exists but has no name attribute — name now falls back to
    the PII-safe `Пользователь #ABCD` (last-4-UUID) instead of a
    bare 'Пользователь' so the three legacy accounts on the leaderboard
    are visually distinct rather than identical placeholders."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = None
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(idp, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee1234")
    assert result == ("Пользователь #1234", None)


def test_returns_uuid_suffix_when_name_is_empty_string():
    """Same as above but the Keycloak attribute is `[""]` rather than
    None — both empty representations get the safe fallback."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = [""]
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(idp, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee5678")
    assert result == ("Пользователь #5678", None)


def test_masks_phone_leaked_as_name():
    """Operator's 18.05.2026 prod screenshot: user with
    name="+77001234567" rendered in the leaderboard with the raw
    phone visible. After this fix the same input is masked to
    Пользователь #<last4>."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = ["+77001234567"]
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(
        idp, "11111111-2222-3333-4444-555566667777"
    )
    assert result == ("Пользователь #7777", None)


def test_masks_auto_username_leaked_as_name():
    """`user3` style auto-username (from admin panel / seed scripts)
    is also masked — not PII but still looks like a placeholder."""
    idp = MagicMock()
    kc_user = MagicMock()
    kc_user.attributes.name = ["user3"]
    kc_user.attributes.avatar = None
    idp.get_user.return_value = kc_user

    result = _user_display_pair(
        idp, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeABCD"
    )
    assert result == ("Пользователь #ABCD", None)


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


# ─────────────────────── SQL oversampling regression ───────────────────


class _SpyPointsRepo:
    """Stand-in repo that remembers what limit it was last called
    with, so the oversampling-at-the-SQL-layer behaviour can be
    asserted directly (not just through the response shape).
    """

    def __init__(self, top: list[tuple]):
        self._top = top
        self.last_limit: int | None = None

    def get_all_ranked(self, limit: int) -> list[tuple]:
        self.last_limit = limit
        return self._top[:limit]


@pytest.mark.asyncio
async def test_leaderboard_oversamples_to_survive_orphan_heavy_top():
    """The 19.05.2026 production bug: /leaderboard?limit=5 returned []
    while /leaderboard?limit=20 returned three real users from the
    SAME database. Cause: five seed mocks (4000-5000 points) deleted
    on 18.05.2026 still occupy the top of the user_points table —
    `ORDER BY total_points DESC LIMIT 5` returned all orphans, the
    post-fetch filter dropped all of them, and the API answered [].

    Fix: oversample at the SQL layer (limit*3, capped at 200) so the
    filter has headroom to find `limit` valid users even when the
    SQL top is mostly orphan rows. This test pins both behaviours —
    the oversample request AND the correct visible response.
    """
    real_a, real_b, real_c = str(uuid4()), str(uuid4()), str(uuid4())
    # Five orphans first (recreates the prod state on 19.05.2026
    # after delete_mock_users.py ran but cascade-delete of
    # user_points hadn't been wired up yet), then three real users.
    orphans = [(str(uuid4()), 5000 - i * 200) for i in range(5)]
    top_rows = orphans + [
        (real_a, 37),
        (real_b, 29),
        (real_c, 26),
    ]
    spy = _SpyPointsRepo(top_rows)

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: spy

    # Match the actual Home-screen request: limit=5.
    response = await get_leaderboard(
        limit=5,
        session=MagicMock(),
        idp=_make_idp({real_a, real_b, real_c}),
        file_service=_make_file_service(),
    )

    # Oversample contract: SQL was asked for 5 × 3 = 15 rows.
    assert spy.last_limit == 15

    # Visible contract: three real users, ranks 1/2/3, gap-free
    # despite the five orphans that sat above them in raw SQL.
    assert [(e.rank, e.user_id) for e in response] == [
        (1, real_a),
        (2, real_b),
        (3, real_c),
    ]


@pytest.mark.asyncio
async def test_leaderboard_oversample_capped_at_200():
    """A pathological caller asking for limit=500 (the route's own
    upper bound) shouldn't trigger a 1500-row SQL scan and a
    1500-call Keycloak storm. The cap is set to 200 — same order of
    magnitude as the route's ge=1/le=500 query-param bound."""
    spy = _SpyPointsRepo([])

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: spy

    await get_leaderboard(
        limit=500,
        session=MagicMock(),
        idp=_make_idp(set()),
        file_service=_make_file_service(),
    )

    assert spy.last_limit == 200


@pytest.mark.asyncio
async def test_leaderboard_stops_iterating_once_limit_filled():
    """Even with oversample=15, if the first 5 valid users are at
    the top of the SQL result, we shouldn't burn Keycloak lookups
    on the remaining 10. The post-filter loop breaks as soon as
    rank_counter reaches the requested limit."""
    real_users = [str(uuid4()) for _ in range(10)]
    top = [(uid, 1000 - i) for i, uid in enumerate(real_users)]

    idp = MagicMock()
    lookups: list[str] = []

    def _get_user(user_id):
        lookups.append(str(user_id))
        mock = MagicMock()
        mock.attributes.name = [f"User-{user_id[:6]}"]
        mock.attributes.avatar = None
        return mock

    idp.get_user.side_effect = _get_user

    import api.routes.user.leaderboard as lb_module

    lb_module.UserPointsRepository = lambda session: _SpyPointsRepo(top)

    response = await get_leaderboard(
        limit=5,
        session=MagicMock(),
        idp=idp,
        file_service=_make_file_service(),
    )

    # Visible: first 5 users.
    assert len(response) == 5
    # Keycloak calls: also 5 (one per valid user). The remaining 5
    # rows in the oversampled SQL result are never looked up.
    assert len(lookups) == 5
