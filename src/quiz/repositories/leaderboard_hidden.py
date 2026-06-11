"""Thin DB layer for the `leaderboard_hidden_users` table.

No business logic — that lives in the service. Three primitives:

- `get_all()`        — current hidden set as a list of str user_ids.
- `add(user_ids)`    — bulk INSERT … ON CONFLICT DO NOTHING (idempotent).
- `remove(user_ids)` — bulk DELETE of the given user_ids (idempotent).

Bulk INSERT uses Postgres `ON CONFLICT DO NOTHING` so re-hiding an
already-hidden user is a no-op without an extra read. Bulk DELETE uses
an `IN (:ids)` with an expanding bindparam — the same proven list-binding
pattern used elsewhere in this repo (ent_attempts kk-splice) so it works
cleanly under psycopg2 with no array-cast ambiguity.

The route owns the commit (mirrors leaderboard-prizes / app_update_config):
the service flushes, the route commits after a successful save.
"""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from quiz.models.leaderboard_hidden import LeaderboardHiddenUser


class LeaderboardHiddenRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> list[str]:
        """Все скрытые user_id (как строки, для отдачи фронту)."""
        rows = self.db.query(LeaderboardHiddenUser.user_id).all()
        return [str(r[0]) for r in rows]

    def add(self, user_ids: list[str]) -> None:
        """Bulk-вставка с ON CONFLICT DO NOTHING — идемпотентно.

        psycopg2 адаптирует строковые UUID к колонке UUID на стороне
        драйвера, явный cast не нужен."""
        if not user_ids:
            return
        stmt = (
            pg_insert(LeaderboardHiddenUser)
            .values([{"user_id": uid} for uid in user_ids])
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        self.db.execute(stmt)

    def remove(self, user_ids: list[str]) -> None:
        """Bulk-удаление переданных user_id — идемпотентно.

        `IN (:ids)` с expanding bindparam — тот же приём для списков,
        что и в ent_attempts (kk-splice), работает под psycopg2."""
        if not user_ids:
            return
        stmt = text(
            "DELETE FROM leaderboard_hidden_users WHERE user_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        self.db.execute(stmt, {"ids": user_ids})
