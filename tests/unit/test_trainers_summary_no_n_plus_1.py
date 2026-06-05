"""Unit tests for the N+1 fix in ProgressService.get_trainers_progress_summary.

Previously the summary checked each of the ~hundreds of trainers individually
(`_has_trainer_attempts`), opening a fresh DB session per trainer — ~17s for a
user with no attempts. It now fetches the set of attempted trainer ids in a
single query and only processes those.

These tests use a fake Unit of Work with call counters — no DB.
"""

import pytest

from quiz.services.progress import ProgressService


class _FakeTrainer:
    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name


class _FakeTrainersRepo:
    def __init__(self, trainers):
        self._trainers = trainers

    def get_all_trainers(self):
        return self._trainers


class _FakeTrainerAttemptsRepo:
    def __init__(self, attempted_ids):
        self._ids = set(attempted_ids)
        self.batch_calls = 0
        self.per_trainer_calls = 0

    def get_trainer_ids_with_attempts(self, user_id):
        self.batch_calls += 1
        return set(self._ids)

    # The old per-trainer paths — must NOT be called by the summary anymore.
    def get_attempt_count(self, user_id, trainer_id):
        self.per_trainer_calls += 1
        return 1 if trainer_id in self._ids else 0

    def get_best_attempt_for_trainer(self, user_id, trainer_id):
        self.per_trainer_calls += 1
        return None


class _FakeUoW:
    def __init__(self, trainers, attempted_ids):
        self.trainers = _FakeTrainersRepo(trainers)
        self.trainer_attempts = _FakeTrainerAttemptsRepo(attempted_ids)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_zero_attempts_no_per_trainer_queries():
    trainers = [_FakeTrainer(i, f"T{i}") for i in range(1, 555)]  # 554 trainers
    uow = _FakeUoW(trainers, attempted_ids=set())
    svc = ProgressService(uow, cache_service=None)  # cache off → runs real body

    result = svc.get_trainers_progress_summary("user-1")

    # One batch query, zero per-trainer existence checks (N+1 eliminated).
    assert uow.trainer_attempts.batch_calls == 1
    assert uow.trainer_attempts.per_trainer_calls == 0
    assert result.total_trainers == 554
    assert result.completed_trainers == 0
    assert result.overall_progress == 0.0


def test_only_attempted_trainers_processed(monkeypatch):
    trainers = [_FakeTrainer(i, f"T{i}") for i in range(1, 6)]  # 5 trainers
    uow = _FakeUoW(trainers, attempted_ids={2, 4})
    svc = ProgressService(uow, cache_service=None)
    # Avoid the heavy per-attempt progress computation; fix progress at 0.5.
    monkeypatch.setattr(svc, "get_trainer_progress", lambda user_id, trainer_id: 0.5)

    result = svc.get_trainers_progress_summary("user-1")

    assert uow.trainer_attempts.batch_calls == 1
    assert result.total_trainers == 5
    assert result.completed_trainers == 2
    # overall = sum(progress)/total = (0.5 + 0.5) / 5 = 0.2
    assert abs(result.overall_progress - 0.2) < 1e-6


def test_no_trainers_returns_zero():
    uow = _FakeUoW(trainers=[], attempted_ids=set())
    svc = ProgressService(uow, cache_service=None)

    result = svc.get_trainers_progress_summary("user-1")

    assert result.total_trainers == 0
    assert result.completed_trainers == 0
    assert result.overall_progress == 0.0
