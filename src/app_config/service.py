"""Settings reads go through a 60-second Redis cache.

Admin writes invalidate the cache key for the affected setting so the
new value propagates to all backend replicas within at most one cache
TTL. Reads fall through to the DB and refill the cache on miss. If
Redis is down for any reason, the service still works — the cache
layer just becomes a passthrough, every call hits the DB. Don't make
the cache layer mandatory; an outage in Redis must not take SMS-auth
offline.
"""

import logging

from redis import Redis, RedisError

from app_config.dtos import AppSettingDTO
from app_config.repository import AppSettingsRepository

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_CACHE_PREFIX = "app_settings:v1:"


class AppSettingsService:
    def __init__(self, repo: AppSettingsRepository, redis: Redis):
        self.repo = repo
        self.redis = redis

    # ─────── public reads (used by guards / business logic) ───────

    def get_int(self, key: str, default: int) -> int:
        """Convenience for numeric settings. Returns `default` if the row
        is missing or its value can't be parsed as int — a misconfigured
        admin save should never crash auth flow."""
        raw = self.get_raw(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning(
                "[app_settings] value for %r is not int (%r), falling back to default %d",
                key,
                raw,
                default,
            )
            return default

    def get_raw(self, key: str) -> str | None:
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        row = self.repo.get(key)
        if row is None:
            return None
        self._cache_set(key, row.value)
        return row.value

    # ─────── admin CRUD ───────

    def list_all(self) -> list[AppSettingDTO]:
        return [AppSettingDTO.model_validate(r) for r in self.repo.list_all()]

    def get_one(self, key: str) -> AppSettingDTO | None:
        row = self.repo.get(key)
        return AppSettingDTO.model_validate(row) if row else None

    def update_value(self, key: str, value: str) -> AppSettingDTO | None:
        row = self.repo.update_value(key, value)
        if row is None:
            return None
        # Bust the cache so the next caller sees the new value within
        # millis, not at the end of the TTL window.
        self._cache_delete(key)
        return AppSettingDTO.model_validate(row)

    # ─────── cache helpers ───────

    def _cache_key(self, key: str) -> str:
        return f"{_CACHE_PREFIX}{key}"

    def _cache_get(self, key: str) -> str | None:
        try:
            raw = self.redis.get(self._cache_key(key))
        except RedisError as e:
            logger.warning("[app_settings] cache read failed for %r: %s", key, e)
            return None
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    def _cache_set(self, key: str, value: str) -> None:
        try:
            self.redis.setex(self._cache_key(key), _CACHE_TTL_SECONDS, value)
        except RedisError as e:
            logger.warning("[app_settings] cache write failed for %r: %s", key, e)

    def _cache_delete(self, key: str) -> None:
        try:
            self.redis.delete(self._cache_key(key))
        except RedisError as e:
            logger.warning("[app_settings] cache invalidation failed for %r: %s", key, e)
