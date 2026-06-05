"""Unit tests for the N+1 fix in ProgressService.get_ent_options_progress_summary.

Same class of bug as the trainers fix: the summary checked each ENT option
individually (`_has_ent_option_attempts`), opening a DB session per option. It
now fetches the set of attempted option ids in a single query and only
processes those. Fake Unit of Work with call counters — no DB.
"""

import pytest

from quiz.services.progress import ProgressService


class _FakeOption:
    def __init__(self, id: int):
        self.id = id
        self.option_number = id


class _FakeEntOptionsRepo:
    def __init__(self, options):
        self._options = options

    def get_all_ent_options(self, page: int = 1, page_size: int = 1000):
        return self._options, len(self._options)


class _FakeEntAttemptsRepo:
    def __init__(self, attempted_ids):
        self._ids = set(attempted_ids)
        self.batch_calls = 0
        self.per_item_calls = 0

    def get_ent_option_ids_with_attempts(self, user_id):
        self.batch_calls += 1
        return set(self._ids)

    # Old per-item paths — must NOT be called by the summary anymore.
    def get_attempt_count(self, user_id, ent_option_id):
        self.per_item_calls += 1
        return 1 if ent_option_id in self._ids else 0

    def get_best_attempt_for_option(self, user_id, ent_option_id):
        self.per_item_calls += 1
        return None


class _FakeUoW:
    def __init__(self, options, attempted_ids):
        self.ent_options = _FakeEntOptionsRepo(options)
        self.ent_attempts = _FakeEntAttemptsRepo(attempted_ids)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_zero_attempts_no_per_option_queries():
    options = [_FakeOption(i) for i in range(1, 81)]  # 80 ENT options
    uow = _FakeUoW(options, attempted_ids=set())
    svc = ProgressService(uow, cache_service=None)  # cache off → runs real body

    result = svc.get_ent_options_progress_summary("user-1")

    assert uow.ent_attempts.batch_calls == 1
    assert uow.ent_attempts.per_item_calls == 0  # N+1 eliminated
    assert result.total_options == 80
    assert result.completed_options == 0
    assert result.overall_progress == 0.0


def test_only_attempted_options_processed(monkeypatch):
    options = [_FakeOption(i) for i in range(1, 6)]  # 5 options
    uow = _FakeUoW(options, attempted_ids={2, 4})
    svc = ProgressService(uow, cache_service=None)
    monkeypatch.setattr(svc, "get_ent_option_progress", lambda user_id, option_id: 0.5)

    result = svc.get_ent_options_progress_summary("user-1")

    assert uow.ent_attempts.batch_calls == 1
    assert result.total_options == 5
    assert result.completed_options == 2
    # overall = sum(progress)/total = (0.5 + 0.5) / 5 = 0.2
    assert abs(result.overall_progress - 0.2) < 1e-6


def test_no_options_returns_zero():
    uow = _FakeUoW(options=[], attempted_ids=set())
    svc = ProgressService(uow, cache_service=None)

    result = svc.get_ent_options_progress_summary("user-1")

    assert result.total_options == 0
    assert result.completed_options == 0
    assert result.overall_progress == 0.0
