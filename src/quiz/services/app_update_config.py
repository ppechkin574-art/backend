"""Business logic for the admin-controlled app force-update config.

Singleton row (id=1). `get()` returns it (get-or-create), `update()`
applies the provided fields + stamps `updated_by` / `updated_at`.

The route owns the commit (mirrors leaderboard-prizes) so the admin PUT
flushes here and commits in the route after a successful save.
"""

import logging

from datetime import UTC, datetime

from quiz.dtos.app_update_config import AppUpdateConfigUpdateDTO
from quiz.models.app_update_config import AppUpdateConfig
from quiz.repositories.app_update_config import AppUpdateConfigRepository

logger = logging.getLogger(__name__)


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

        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(config, field, value)

        config.updated_by = updated_by
        # Explicit stamp so the value is consistent even when no column
        # changed (onupdate only fires on a real column UPDATE).
        config.updated_at = datetime.now(UTC)

        self.repo.db.flush()
        return config
