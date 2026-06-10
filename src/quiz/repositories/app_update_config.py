"""Thin DB layer for the singleton `app_update_config` table.

No business logic — that lives in the service. The row id is always 1.
`get_or_create` guarantees the row exists (the migration seeds it, but
this is belt-and-braces so reads never NULL out if the seed was skipped).
"""

from sqlalchemy.orm import Session

from quiz.models.app_update_config import AppUpdateConfig

SINGLETON_ID = 1


class AppUpdateConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self) -> AppUpdateConfig:
        """Return the singleton row (id=1), creating it with defaults if
        it does not exist yet."""
        row = self.db.get(AppUpdateConfig, SINGLETON_ID)
        if row is None:
            row = AppUpdateConfig(
                id=SINGLETON_ID,
                ios_min_build=0,
                android_min_build=0,
                ios_store_url="",
                android_store_url="",
            )
            self.db.add(row)
            self.db.flush()
        return row
