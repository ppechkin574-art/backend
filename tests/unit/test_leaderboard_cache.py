"""Leaderboard display-name cache (`_cached_display_pair`).

Proves the speedup contract: a repeat render is served from Redis and does NOT
hit Keycloak; the orphan (deleted-user) result is negative-cached; the transient
Keycloak-outage placeholder is NEVER cached (so it refreshes on recovery).
"""

from unittest.mock import MagicMock

# Eager imports so SQLAlchemy mappers resolve (mirrors test_leaderboard_orphan_filter).
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from api.routes.user.leaderboard import _cached_display_pair
from clients.identity_provider import IdentityNotFound


class _FakeCache:
    """Minimal in-memory CacheService stand-in (make_key / get / set)."""

    def __init__(self):
        self.store: dict = {}

    def make_key(self, strategy, **kw):
        return f"{kw.get('resource')}:{kw.get('params')}"

    def get(self, key, return_type=None):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True


def _idp_with_name(name="Иван", avatar="a.jpg"):
    idp = MagicMock()
    user = MagicMock()
    user.attributes.name = [name]
    user.attributes.avatar = [avatar] if avatar else None
    idp.get_user.return_value = user
    return idp


def test_cache_hit_skips_keycloak():
    idp = _idp_with_name("Иван", "a.jpg")
    cache = _FakeCache()

    assert _cached_display_pair(idp, cache, "u1") == ("Иван", "a.jpg")
    assert idp.get_user.call_count == 1  # cold → one Keycloak call

    assert _cached_display_pair(idp, cache, "u1") == ("Иван", "a.jpg")
    assert idp.get_user.call_count == 1  # warm → served from cache, no extra call


def test_orphan_is_negative_cached():
    idp = MagicMock()
    idp.get_user.side_effect = IdentityNotFound
    cache = _FakeCache()

    assert _cached_display_pair(idp, cache, "gone") is None
    assert _cached_display_pair(idp, cache, "gone") is None
    assert idp.get_user.call_count == 1  # second served from negative cache


def test_transient_placeholder_is_not_cached():
    idp = MagicMock()
    idp.get_user.side_effect = Exception("Keycloak 5xx")
    cache = _FakeCache()

    assert _cached_display_pair(idp, cache, "flaky") == ("Пользователь", None)
    # Must NOT be cached — has to refresh to the real name once Keycloak recovers.
    assert _cached_display_pair(idp, cache, "flaky") == ("Пользователь", None)
    assert idp.get_user.call_count == 2
