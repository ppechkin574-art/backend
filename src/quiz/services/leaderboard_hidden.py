"""Business logic for the admin leaderboard hide-list.

Thin wrapper over the repository:

- `get_hidden()`           — current hidden set (list of str user_ids).
- `set_hidden(ids, hidden)` — bulk hide (hidden=True → add) or show
  (hidden=False → remove), then return the updated full hidden set.

Idempotent: re-hiding an already-hidden user or showing an already-visible
user is a no-op (ON CONFLICT DO NOTHING / DELETE of absent rows).

The route owns the commit (mirrors leaderboard-prizes / app_update_config):
the service flushes here, the route commits after a successful save.
"""

import logging

from quiz.repositories.leaderboard_hidden import LeaderboardHiddenRepository

logger = logging.getLogger(__name__)


class LeaderboardHiddenService:
    def __init__(self, repo: LeaderboardHiddenRepository):
        self.repo = repo

    def get_hidden(self) -> list[str]:
        return self.repo.get_all()

    def set_hidden(self, user_ids: list[str], hidden: bool) -> list[str]:
        """hidden=True → скрыть переданных; hidden=False → показать.
        Возвращает обновлённый полный набор скрытых user_id."""
        # Дедуп на входе — на bulk-вставку/удаление не влияет, но
        # держит лог и поведение предсказуемыми.
        unique_ids = list(dict.fromkeys(user_ids))
        if hidden:
            self.repo.add(unique_ids)
        else:
            self.repo.remove(unique_ids)
        self.repo.db.flush()
        return self.repo.get_all()
