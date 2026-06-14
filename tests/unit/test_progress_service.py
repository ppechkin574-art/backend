"""Unit tests for ProgressService.

Covers:
- get_trainer_progress: no attempt, not completed, all correct, partial, empty questions
- get_ent_option_progress: no attempt, not completed, all correct, weighted partial
- _calculate_streak_days: no dates, today only, consecutive, gap breaks streak
- record_progress: delegates to repo, commits, invalidates cache
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import payments.models  # noqa: F401 — ORM mapper registration
import quiz.models  # noqa: F401
import student.models  # noqa: F401
import subscription.models  # noqa: F401

from quiz.dtos.enums import Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__enter__ = lambda s: s
    uow.__exit__ = MagicMock(return_value=False)
    return uow


def _passthrough_cache() -> MagicMock:
    cache = MagicMock()
    cache.get_or_set.side_effect = lambda key, fn, ttl: fn()
    return cache


def _make_service(uow=None, cache=None):
    from quiz.services.progress import ProgressService

    return ProgressService(
        uow=uow or _make_uow(),
        cache_service=cache or _passthrough_cache(),
    )


def _fake_variant(id: int, is_correct: bool) -> SimpleNamespace:
    return SimpleNamespace(id=id, is_correct=is_correct)


def _fake_answer(variant_id: int | None) -> SimpleNamespace:
    return SimpleNamespace(variant_id=variant_id)


def _fake_question(correct_ids: list[int], chosen_ids: list[int]) -> SimpleNamespace:
    variants = [_fake_variant(i, True) for i in correct_ids]
    variants += [_fake_variant(99, False)]  # always one wrong variant
    answers = [_fake_answer(i) for i in chosen_ids]
    return SimpleNamespace(variants=variants, answers=answers)


def _fake_attempt_with_questions(questions: list, status: Status = Status.completed) -> SimpleNamespace:
    return SimpleNamespace(id=1, status=status, questions=questions)


def _fake_ent_stats(correct=0, incorrect=0, partial_correct=0, skiped=0) -> SimpleNamespace:
    return SimpleNamespace(
        correct=correct,
        incorrect=incorrect,
        partial_correct=partial_correct,
        skiped=skiped,
    )


# ---------------------------------------------------------------------------
# get_trainer_progress
# ---------------------------------------------------------------------------


class TestGetTrainerProgress:
    def test_no_best_attempt_returns_zero(self):
        uow = _make_uow()
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = None
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.0

    def test_not_completed_returns_zero(self):
        uow = _make_uow()
        attempt = SimpleNamespace(id=1, status=Status.in_progress)
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = attempt
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.0

    def test_empty_questions_returns_zero(self):
        uow = _make_uow()
        attempt = SimpleNamespace(id=1, status=Status.completed)
        attempt_with_q = _fake_attempt_with_questions([])
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = attempt
        uow.trainer_attempts.get_with_questions.return_value = attempt_with_q
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.0

    def test_all_correct_returns_1(self):
        uow = _make_uow()
        attempt = SimpleNamespace(id=1, status=Status.completed)
        questions = [
            _fake_question([10], [10]),
            _fake_question([20], [20]),
        ]
        attempt_with_q = _fake_attempt_with_questions(questions)
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = attempt
        uow.trainer_attempts.get_with_questions.return_value = attempt_with_q
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 1.0

    def test_half_correct_returns_half(self):
        uow = _make_uow()
        attempt = SimpleNamespace(id=1, status=Status.completed)
        questions = [
            _fake_question([10], [10]),   # correct
            _fake_question([20], [30]),   # wrong
        ]
        attempt_with_q = _fake_attempt_with_questions(questions)
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = attempt
        uow.trainer_attempts.get_with_questions.return_value = attempt_with_q
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.5

    def test_all_skipped_returns_zero(self):
        uow = _make_uow()
        attempt = SimpleNamespace(id=1, status=Status.completed)
        questions = [
            _fake_question([10], []),  # skipped
            _fake_question([20], []),  # skipped
        ]
        attempt_with_q = _fake_attempt_with_questions(questions)
        uow.trainer_attempts.get_best_attempt_for_trainer.return_value = attempt
        uow.trainer_attempts.get_with_questions.return_value = attempt_with_q
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.0

    def test_exception_in_repo_returns_zero(self):
        uow = _make_uow()
        uow.trainer_attempts.get_best_attempt_for_trainer.side_effect = RuntimeError("DB down")
        svc = _make_service(uow=uow)
        result = svc.get_trainer_progress("u1", trainer_id=1)
        assert result == 0.0


# ---------------------------------------------------------------------------
# get_ent_option_progress
# ---------------------------------------------------------------------------


class TestGetEntOptionProgress:
    def test_no_best_attempt_returns_zero(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = None
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.0

    def test_not_completed_returns_zero(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = SimpleNamespace(
            id=1, status=Status.in_progress, spend_time=0
        )
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.0

    def test_all_correct_returns_1(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = SimpleNamespace(
            id=1, status=Status.completed, spend_time=0
        )
        uow.ent_attempts.get_attempt_statistic.return_value = _fake_ent_stats(
            correct=10, incorrect=0, partial_correct=0, skiped=0
        )
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 1.0

    def test_partial_correct_weighted_half(self):
        # 2 correct + 2 partial → weighted = 2*1.0 + 2*0.5 = 3.0 / 4 = 0.75
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = SimpleNamespace(
            id=1, status=Status.completed, spend_time=0
        )
        uow.ent_attempts.get_attempt_statistic.return_value = _fake_ent_stats(
            correct=2, incorrect=0, partial_correct=2, skiped=0
        )
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.75

    def test_all_incorrect_returns_zero(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = SimpleNamespace(
            id=1, status=Status.completed, spend_time=0
        )
        uow.ent_attempts.get_attempt_statistic.return_value = _fake_ent_stats(
            correct=0, incorrect=5, partial_correct=0, skiped=0
        )
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.0

    def test_no_statistics_returns_zero(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.return_value = SimpleNamespace(
            id=1, status=Status.completed, spend_time=0
        )
        uow.ent_attempts.get_attempt_statistic.return_value = None
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.0

    def test_exception_returns_zero(self):
        uow = _make_uow()
        uow.ent_attempts.get_best_attempt_for_option.side_effect = RuntimeError("timeout")
        svc = _make_service(uow=uow)
        result = svc.get_ent_option_progress("u1", ent_option_id=1)
        assert result == 0.0


# ---------------------------------------------------------------------------
# _calculate_streak_days
# ---------------------------------------------------------------------------


class TestCalculateStreakDays:
    def _make_service_with_dates(self, trainer_dates=None, ent_dates=None):
        uow = _make_uow()
        uow.trainer_attempts.get_completed_dates.return_value = trainer_dates or []
        uow.ent_attempts.get_completed_dates.return_value = ent_dates or []
        return _make_service(uow=uow)

    def test_no_dates_returns_zero(self):
        svc = self._make_service_with_dates()
        assert svc._calculate_streak_days("u1") == 0

    def test_today_only_returns_1(self):
        today = datetime.now(UTC).date()
        svc = self._make_service_with_dates(trainer_dates=[today])
        assert svc._calculate_streak_days("u1") == 1

    def test_yesterday_only_returns_zero(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        svc = self._make_service_with_dates(trainer_dates=[yesterday])
        assert svc._calculate_streak_days("u1") == 0

    def test_today_and_yesterday_returns_2(self):
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        svc = self._make_service_with_dates(trainer_dates=[today, yesterday])
        assert svc._calculate_streak_days("u1") == 2

    def test_consecutive_3_days_returns_3(self):
        today = datetime.now(UTC).date()
        dates = [today - timedelta(days=i) for i in range(3)]
        svc = self._make_service_with_dates(trainer_dates=dates)
        assert svc._calculate_streak_days("u1") == 3

    def test_gap_breaks_streak(self):
        today = datetime.now(UTC).date()
        # today + 3 days ago, skipping yesterday and 2 days ago
        svc = self._make_service_with_dates(
            trainer_dates=[today, today - timedelta(days=3)]
        )
        assert svc._calculate_streak_days("u1") == 1

    def test_merges_trainer_and_ent_dates(self):
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        svc = self._make_service_with_dates(
            trainer_dates=[today],
            ent_dates=[yesterday],
        )
        assert svc._calculate_streak_days("u1") == 2

    def test_deduplicates_duplicate_dates(self):
        today = datetime.now(UTC).date()
        svc = self._make_service_with_dates(
            trainer_dates=[today, today],
            ent_dates=[today],
        )
        assert svc._calculate_streak_days("u1") == 1


# ---------------------------------------------------------------------------
# record_progress
# ---------------------------------------------------------------------------


class TestRecordProgress:
    def test_calls_repo_record_progress(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        svc.record_progress("u1", question_id=5, is_correct=True, attempt_type="trainer", attempt_id=10)
        uow.progress.record_progress.assert_called_once_with(
            user_id="u1",
            question_id=5,
            is_correct=True,
            attempt_type="trainer",
            attempt_id=10,
        )

    def test_commits_after_record(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        svc.record_progress("u1", question_id=1, is_correct=False, attempt_type="ent", attempt_id=2)
        uow.commit.assert_called()

    def test_invalidates_cache(self):
        uow = _make_uow()
        cache = _passthrough_cache()
        svc = _make_service(uow=uow, cache=cache)
        svc.record_progress("u1", question_id=1, is_correct=True, attempt_type="trainer", attempt_id=1)
        cache.invalidate_by_resources.assert_called()
