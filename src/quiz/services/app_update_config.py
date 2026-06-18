"""Business logic for the admin-controlled app force-update config.

Singleton row (id=1). `get()` returns it (get-or-create), `update()`
applies the provided fields + stamps `updated_by` / `updated_at`.

The route owns the commit (mirrors leaderboard-prizes) so the admin PUT
flushes here and commits in the route after a successful save.
"""

import logging

from datetime import UTC, datetime

from sqlalchemy import select

from quiz.dtos.app_update_config import AppUpdateConfigUpdateDTO
from quiz.models.app_update_config import (
    AppUpdateConfig,
    AppUpdateConfigAuditLog,
)
from quiz.repositories.app_update_config import AppUpdateConfigRepository

logger = logging.getLogger(__name__)

# Redis key for the cached PUBLIC `/app/update-config` payload. Bumped to
# v2 when the wire shape changed (added recommended_build) so a deploy can
# never serve a stale, old-shape cached body. Admin saves invalidate it.
PUBLIC_CACHE_KEY = "app_update_config:public:v2"
PUBLIC_CACHE_TTL = 300  # seconds — short; admin saves also invalidate.

# Config fields captured in each audit snapshot (everything an admin edits).
_SNAPSHOT_FIELDS = (
    "ios_min_build",
    "android_min_build",
    "ios_store_url",
    "android_store_url",
    "ios_last_known_build",
    "android_last_known_build",
    "ios_recommended_build",
    "android_recommended_build",
)


def _snapshot(config: AppUpdateConfig) -> dict:
    return {f: getattr(config, f) for f in _SNAPSHOT_FIELDS}


class AppUpdateConfigService:
    def __init__(self, repo: AppUpdateConfigRepository):
        self.repo = repo

    def get(self) -> AppUpdateConfig:
        return self.repo.get_or_create()

    def update(
        self,
        payload: AppUpdateConfigUpdateDTO,
        updated_by: str | None = None,
    ) -> AppUpdateConfig:
        config = self.repo.get_or_create()

        before = _snapshot(config)

        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(config, field, value)

        config.updated_by = updated_by
        # Explicit stamp so the value is consistent even when no column
        # changed (onupdate only fires on a real column UPDATE).
        config.updated_at = datetime.now(UTC)

        after = _snapshot(config)

        # Append-only audit row (only when something actually changed) so
        # the panel can show history and offer one-click rollback.
        if before != after:
            self.repo.db.add(
                AppUpdateConfigAuditLog(
                    changed_by=updated_by,
                    before_values=before,
                    after_values=after,
                )
            )

        self.repo.db.flush()
        return config

    def history(self, limit: int = 50) -> list[AppUpdateConfigAuditLog]:
        """Most-recent-first change history for the panel."""
        stmt = (
            select(AppUpdateConfigAuditLog)
            .order_by(AppUpdateConfigAuditLog.changed_at.desc())
            .limit(limit)
        )
        return list(self.repo.db.execute(stmt).scalars().all())
