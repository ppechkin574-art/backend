"""Cache + DB read/write logic for AppSettingsService.

Covers:
- get_int() — cache miss → DB read → cache set; cache hit short-circuits.
- get_int() — non-int value falls back to default with a warning.
- get_int() — missing key returns default.
- update_value() — DB write + cache invalidation so next read hits DB.
- Redis failures don't break service (logged + fall through to DB or default).

All collaborators are fakes — no real Redis, no real Postgres. Cache TTL
behaviour is verified through the SETEX call signature, not by actually
waiting.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from redis import RedisError

from app_config.service import AppSettingsService


class _FakeRow:
    def __init__(self, key: str, value: str, description: str = ""):
        self.key = key
        self.value = value
        self.description = description
        # AppSettingDTO.model_validate uses from_attributes; pydantic needs
        # an attribute, not a method. updated_at is datetime in real model;
        # here we just use a sentinel string — tests don't validate the
        # DTO shape beyond reading .value.
        from datetime import datetime, timezone

        self.updated_at = datetime(2026, 5, 15, tzinfo=timezone.utc)


class _FakeRepo:
    def __init__(self, store: dict[str, _FakeRow] | None = None):
        self.store = store or {}
        self.get_calls: list[str] = []
        self.update_calls: list[tuple[str, str]] = []

    def get(self, key: str) -> _FakeRow | None:
        self.get_calls.append(key)
        return self.store.get(key)

    def update_value(self, key: str, value: str) -> _FakeRow | None:
        self.update_calls.append((key, value))
        if key not in self.store:
            return None
        self.store[key].value = value
        return self.store[key]

    def list_all(self) -> list[_FakeRow]:
        return list(self.store.values())


class _FakeRedis:
    """Tracks every call so tests can assert cache behaviour. `fail_on`
    controls which methods raise RedisError for the fail-open path tests.
    """

    def __init__(self, fail_on: set[str] | None = None):
        self.kv: dict[str, str] = {}
        self.fail_on = fail_on or set()
        self.calls: list[tuple[str, Any]] = []

    def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key))
        if "get" in self.fail_on:
            raise RedisError("simulated redis-down")
        raw = self.kv.get(key)
        return raw.encode() if raw is not None else None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.calls.append(("setex", (key, ttl, value)))
        if "setex" in self.fail_on:
            raise RedisError("simulated redis-down")
        self.kv[key] = value

    def delete(self, key: str) -> int:
        self.calls.append(("delete", key))
        if "delete" in self.fail_on:
            raise RedisError("simulated redis-down")
        return 1 if self.kv.pop(key, None) is not None else 0


def _make_service(rows: dict[str, _FakeRow] | None = None, redis_fail: set[str] | None = None):
    repo = _FakeRepo(rows or {})
    redis = _FakeRedis(redis_fail)
    return AppSettingsService(repo, redis), repo, redis


def test_get_int_returns_int_value_from_db_on_cache_miss():
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1500")}
    svc, repo, redis = _make_service(rows)

    result = svc.get_int("sms_daily_cap", default=1000)

    assert result == 1500
    assert repo.get_calls == ["sms_daily_cap"]
    # cache populated on miss → SETEX with 60s TTL
    setex_calls = [c for c in redis.calls if c[0] == "setex"]
    assert len(setex_calls) == 1
    assert setex_calls[0][1][1] == 60  # TTL


def test_get_int_cache_hit_skips_db_read():
    """Second call within TTL must not touch the repo."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1500")}
    svc, repo, _redis = _make_service(rows)

    first = svc.get_int("sms_daily_cap", default=1000)
    second = svc.get_int("sms_daily_cap", default=1000)

    assert first == second == 1500
    # repo.get called exactly once — second hit served from cache
    assert repo.get_calls == ["sms_daily_cap"]


def test_get_int_missing_key_returns_default_and_does_not_cache():
    svc, repo, redis = _make_service(rows={})

    result = svc.get_int("nonexistent_key", default=42)

    assert result == 42
    assert repo.get_calls == ["nonexistent_key"]
    # No SETEX for missing rows — we don't want to poison the cache with
    # nulls that would mask a subsequent migration that adds the key.
    assert not any(c[0] == "setex" for c in redis.calls)


def test_get_int_non_int_value_falls_back_to_default():
    """Operator typo in admin panel must not crash auth flow. We log a
    warning and use the safe default."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "not-a-number")}
    svc, _repo, _redis = _make_service(rows)

    result = svc.get_int("sms_daily_cap", default=1000)

    assert result == 1000


def test_get_int_empty_string_falls_back_to_default():
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "")}
    svc, _repo, _redis = _make_service(rows)

    # Empty string evaluates to None-like in our get_raw path; check_raw
    # treats it as a real (empty) cached value, then int("") raises and
    # we fall back to default.
    result = svc.get_int("sms_daily_cap", default=777)
    assert result == 777


def test_get_int_redis_read_failure_falls_through_to_db():
    """If Redis is down, reads must still work via DB so SMS-auth stays
    online during a Redis outage."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1500")}
    svc, _repo, _redis = _make_service(rows, redis_fail={"get"})

    result = svc.get_int("sms_daily_cap", default=1000)

    assert result == 1500


def test_get_int_redis_write_failure_does_not_break_read():
    """SETEX failure is swallowed — the value was still loaded from DB
    so the caller gets the correct number; only the cache layer is
    impacted (next call hits DB again)."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1500")}
    svc, _repo, _redis = _make_service(rows, redis_fail={"setex"})

    result = svc.get_int("sms_daily_cap", default=1000)

    assert result == 1500


def test_update_value_busts_cache_so_next_read_hits_db():
    """Admin saves new value → cache refreshed WRITE-THROUGH (setex with
    the new value, not delete: auth/services.py reads Redis directly with
    no DB fallback, so deleting the key would break auto-subscription on
    registration — see AppSettingsService.update_value) → next read
    reflects the change immediately."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1000")}
    svc, repo, redis = _make_service(rows)

    # Prime cache
    first = svc.get_int("sms_daily_cap", default=0)
    assert first == 1000

    # Admin update
    updated = svc.update_value("sms_daily_cap", "2000")
    assert updated is not None
    assert updated.value == "2000"
    assert repo.update_calls == [("sms_daily_cap", "2000")]

    # Write-through: the cache key now holds the NEW value
    assert any(
        c[0] == "setex" and "sms_daily_cap" in c[1][0] and c[1][2] == "2000"
        for c in redis.calls
    ), f"expected write-through setex with new value, got: {redis.calls}"

    # Next read returns the new value
    second = svc.get_int("sms_daily_cap", default=0)
    assert second == 2000


def test_update_value_returns_none_for_missing_key():
    svc, _repo, _redis = _make_service(rows={})

    result = svc.update_value("does_not_exist", "anything")

    assert result is None


def test_list_all_returns_all_rows_as_dtos():
    rows = {
        "sms_daily_cap": _FakeRow("sms_daily_cap", "1000"),
        "sms_ip_daily_block": _FakeRow("sms_ip_daily_block", "20"),
    }
    svc, _repo, _redis = _make_service(rows)

    result = svc.list_all()

    assert len(result) == 2
    keys = {r.key for r in result}
    assert keys == {"sms_daily_cap", "sms_ip_daily_block"}


def test_cache_keys_are_namespaced():
    """Multiple settings shouldn't collide on cache keys. The service
    uses a version prefix `app_settings:v1:` so a future schema change
    can bump the prefix without poisoning the existing cache."""
    rows = {"sms_daily_cap": _FakeRow("sms_daily_cap", "1500")}
    svc, _repo, redis = _make_service(rows)

    svc.get_int("sms_daily_cap", default=0)

    setex_calls = [c for c in redis.calls if c[0] == "setex"]
    assert any("app_settings:v1:sms_daily_cap" in c[1][0] for c in setex_calls)
