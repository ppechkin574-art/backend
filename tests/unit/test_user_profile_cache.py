"""Unit tests for profile caching in UserRepositoryKeycloak.

`get_user_from_token` resolves the user from Keycloak with two network
round-trips (get user + get roles). Those are now cached in Redis keyed by
`sub`, so repeated authenticated requests within the TTL serve from cache.
Writes through IdentityProviderClientKeycloak invalidate the key.

These tests use a tiny in-memory fake Redis and a fake identity-provider
client with call counters — no network, no real Redis.
"""

from uuid import UUID

import pytest

import auth.repositories.users as users_mod
from auth.dtos import UserDTO
from auth.repositories.users import UserRepositoryKeycloak
from utils.cache import CacheService, CacheStrategy

SUB = UUID("5615ee6c-f8e5-4d65-bc79-3ecf5129a876")


class _FakeRedis:
    """Minimal in-memory Redis: only get / setex / delete are used."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


class _FakeKeycloakUser:
    def __init__(self, user_id: UUID):
        self.id = user_id


class _FakeIDPClient:
    def __init__(self):
        self.get_calls = 0
        self.get_roles_calls = 0

    def get_user_sub_from_token(self, token: str) -> UUID:
        return SUB

    def get(self, query):
        self.get_calls += 1
        return _FakeKeycloakUser(SUB)

    def get_roles(self, user_id):
        self.get_roles_calls += 1
        return ["user"]


@pytest.fixture
def _patch_to_user_dto(monkeypatch):
    # Bypass the real converter so the test doesn't need a full KeycloakUserDTO.
    def _fake(user, roles):
        return UserDTO(
            id=user.id, username="kuda", name="Kuda", is_active=True, roles=list(roles)
        )

    monkeypatch.setattr(users_mod, "to_user_dto", _fake)


def _make_repo():
    cache = CacheService(_FakeRedis(), default_ttl=60)
    idp = _FakeIDPClient()
    repo = UserRepositoryKeycloak(idp, cache_service=cache)
    return repo, idp, cache


def test_second_call_served_from_cache(_patch_to_user_dto):
    repo, idp, _ = _make_repo()

    first = repo.get_user_from_token("token")
    second = repo.get_user_from_token("token")

    assert first.id == SUB
    assert second.id == SUB
    # Keycloak hit only on the first call; second served from Redis.
    assert idp.get_calls == 1
    assert idp.get_roles_calls == 1


def test_invalidation_forces_refetch(_patch_to_user_dto):
    repo, idp, cache = _make_repo()

    repo.get_user_from_token("token")
    # Invalidate exactly the way the client's write methods do.
    key = cache.make_key(CacheStrategy.USER, user_id=SUB, resource="profile")
    cache.delete(key)
    repo.get_user_from_token("token")

    assert idp.get_calls == 2
    assert idp.get_roles_calls == 2


def test_no_cache_still_works(_patch_to_user_dto):
    # Backward-compat: repo without a cache service fetches every time.
    idp = _FakeIDPClient()
    repo = UserRepositoryKeycloak(idp, cache_service=None)

    repo.get_user_from_token("token")
    repo.get_user_from_token("token")

    assert idp.get_calls == 2
    assert idp.get_roles_calls == 2


def test_cached_roles_preserved(_patch_to_user_dto):
    repo, _, _ = _make_repo()

    first = repo.get_user_from_token("token")
    second = repo.get_user_from_token("token")

    assert first.roles == ["user"]
    assert second.roles == ["user"]  # survived serialize/deserialize round-trip
