"""Unit tests for TrainerAttemptService.

Covers:
- _build_finish_attempt_response: pure correctness/scoring/skipped logic
- AttemptValidator: validate_attempt_exists, validate_attempt_not_completed
- finish_attempt: already-completed guard (AttemptCompleted), normal flow calls cashback
- get_attempt_result: ownership guard (PermissionError), status guard (AttemptNotCompleted),
  not-found guard (TrainerAttemptNotExist)
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import payments.models  # noqa: F401 — ORM mapper registration
import pytest
import quiz.models  # noqa: F401
import student.models  # noqa: F401
import subscription.models  # noqa: F401

from quiz.dtos.enums import Status
from quiz.exceptions import (
    AttemptCompleted,
    AttemptNotCompleted,
    TrainerAttemptNotExist,
    WrongStudent,
)
from quiz.utils.validation.attempt_validator import AttemptValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STARTED = datetime(2026, 6, 1, 10, 0, 0)
_COMPLETED = datetime(2026, 6, 1, 10, 30, 0)


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__enter__ = lambda s: s
    uow.__exit__ = MagicMock(return_value=False)
    return uow


def _make_service(uow=None, cache=None, module_lesson=None, cashback=None):
    from quiz.services.trainer_attempts import TrainerAttemptService

    return TrainerAttemptService(
        uow=uow or _make_uow(),
        cache_service=cache or MagicMock(),
        module_lesson_service=module_lesson or MagicMock(),
        cashback_service=cashback or MagicMock(),
    )


def _fake_variant(id: int, is_correct: bool) -> SimpleNamespace:
    return SimpleNamespace(id=id, is_correct=is_correct)


def _fake_answer(variant_id: int | None) -> SimpleNamespace:
    return SimpleNamespace(variant_id=variant_id)


def _fake_question(
    id: int = 1,
    correct_variant_ids: list[int] | None = None,
    chosen_variant_ids: list[int] | None = None,
    spend_time: int = 0,
) -> SimpleNamespace:
    if correct_variant_ids is None:
        correct_variant_ids = [10]
    variants = [_fake_variant(v, True) for v in correct_variant_ids]
    # add one wrong variant always
    variants.append(_fake_variant(99 + id, False))

    answers = [_fake_answer(v) for v in (chosen_variant_ids or [])]

    return SimpleNamespace(
        id=id,
        type="single_choice",
        blocks=[],
        hints=None,
        variants=variants,
        answers=answers,
        spend_time=spend_time,
    )


def _fake_attempt(
    student_guid: UUID | None = None,
    status: Status = Status.in_progress,
    questions: list | None = None,
    score: int = 0,
    trainer_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        student_guid=student_guid or uuid4(),
        trainer_id=trainer_id,
        status=status,
        started_at=_STARTED,
        completed_at=_COMPLETED if status == Status.completed else None,
        score=score,
        questions=questions or [],
        topic_id=None,
    )


# ---------------------------------------------------------------------------
# AttemptValidator — pure unit tests
# ---------------------------------------------------------------------------


class TestAttemptValidator:
    def test_validate_exists_none_raises(self):
        with pytest.raises(TrainerAttemptNotExist):
            AttemptValidator.validate_attempt_exists(None, 1, uuid4())

    def test_validate_exists_wrong_student_raises(self):
        owner = uuid4()
        other = uuid4()
        attempt = _fake_attempt(student_guid=owner, status=Status.in_progress)
        with pytest.raises(WrongStudent):
            AttemptValidator.validate_attempt_exists(attempt, attempt.id, other)

    def test_validate_exists_correct_student_no_raise(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid)
        AttemptValidator.validate_attempt_exists(attempt, attempt.id, student_guid)

    def test_validate_not_completed_in_progress_no_raise(self):
        attempt = _fake_attempt(status=Status.in_progress)
        AttemptValidator.validate_attempt_not_completed(attempt)

    def test_validate_not_completed_completed_raises(self):
        attempt = _fake_attempt(status=Status.completed)
        with pytest.raises(AttemptCompleted):
            AttemptValidator.validate_attempt_not_completed(attempt)


# ---------------------------------------------------------------------------
# _build_finish_attempt_response — pure scoring logic
# ---------------------------------------------------------------------------


class TestBuildFinishAttemptResponse:
    def test_empty_questions_all_zeros(self):
        svc = _make_service()
        attempt = _fake_attempt(questions=[])
        r = svc._build_finish_attempt_response(attempt)
        assert r.total_questions == 0
        assert r.correct_answers == 0
        assert r.incorrect_answers == 0
        assert r.skipped_answers == 0
        assert r.total_spend_time == 0.0

    def test_single_correct_question(self):
        svc = _make_service()
        q = _fake_question(
            id=1,
            correct_variant_ids=[10],
            chosen_variant_ids=[10],
            spend_time=30,
        )
        attempt = _fake_attempt(questions=[q])
        r = svc._build_finish_attempt_response(attempt)
        assert r.total_questions == 1
        assert r.correct_answers == 1
        assert r.incorrect_answers == 0
        assert r.skipped_answers == 0
        assert 1 in r.correct_question_ids

    def test_single_incorrect_question(self):
        svc = _make_service()
        q = _fake_question(
            id=1,
            correct_variant_ids=[10],
            chosen_variant_ids=[20],  # wrong variant
            spend_time=15,
        )
        attempt = _fake_attempt(questions=[q])
        r = svc._build_finish_attempt_response(attempt)
        assert r.correct_answers == 0
        assert r.incorrect_answers == 1
        assert r.skipped_answers == 0
        assert 1 in r.incorrect_question_ids

    def test_skipped_question_has_no_answers(self):
        svc = _make_service()
        q = _fake_question(
            id=1,
            correct_variant_ids=[10],
            chosen_variant_ids=[],  # no answers → skipped
        )
        attempt = _fake_attempt(questions=[q])
        r = svc._build_finish_attempt_response(attempt)
        assert r.skipped_answers == 1
        assert r.correct_answers == 0
        assert r.incorrect_answers == 0

    def test_mixed_questions(self):
        svc = _make_service()
        q_correct = _fake_question(1, [10], [10], spend_time=10)
        q_incorrect = _fake_question(2, [20], [30], spend_time=5)
        q_skipped = _fake_question(3, [40], [], spend_time=0)
        attempt = _fake_attempt(questions=[q_correct, q_incorrect, q_skipped])
        r = svc._build_finish_attempt_response(attempt)
        assert r.total_questions == 3
        assert r.correct_answers == 1
        assert r.incorrect_answers == 1
        assert r.skipped_answers == 1
        assert r.total_spend_time == 15.0

    def test_spend_time_accumulates(self):
        svc = _make_service()
        questions = [
            _fake_question(i, [i * 10], [i * 10], spend_time=i * 5)
            for i in range(1, 5)
        ]
        attempt = _fake_attempt(questions=questions)
        r = svc._build_finish_attempt_response(attempt)
        assert r.total_spend_time == sum(i * 5 for i in range(1, 5))

    def test_average_time_per_question(self):
        svc = _make_service()
        questions = [
            _fake_question(1, [10], [10], spend_time=20),
            _fake_question(2, [20], [20], spend_time=40),
        ]
        attempt = _fake_attempt(questions=questions)
        r = svc._build_finish_attempt_response(attempt)
        assert r.average_time_per_question == 30.0

    def test_score_from_attempt_when_set(self):
        svc = _make_service()
        q = _fake_question(1, [10], [10])
        attempt = _fake_attempt(questions=[q], score=99)
        r = svc._build_finish_attempt_response(attempt)
        assert r.score == 99

    def test_score_falls_back_to_correct_count(self):
        svc = _make_service()
        q = _fake_question(1, [10], [10])
        attempt = _fake_attempt(questions=[q], score=0)
        r = svc._build_finish_attempt_response(attempt)
        assert r.score == 1

    def test_attempt_id_and_trainer_id_preserved(self):
        svc = _make_service()
        attempt = _fake_attempt(questions=[], trainer_id=7)
        r = svc._build_finish_attempt_response(attempt)
        assert r.attempt_id == attempt.id
        assert r.trainer_id == 7

    def test_multiple_correct_variants_exact_match(self):
        svc = _make_service()
        q = _fake_question(1, [10, 20], [10, 20])
        attempt = _fake_attempt(questions=[q])
        r = svc._build_finish_attempt_response(attempt)
        assert r.correct_answers == 1

    def test_multiple_correct_variants_partial_incorrect(self):
        svc = _make_service()
        q = _fake_question(1, [10, 20], [10])  # only one of two correct → incorrect
        attempt = _fake_attempt(questions=[q])
        r = svc._build_finish_attempt_response(attempt)
        assert r.correct_answers == 0
        assert r.incorrect_answers == 1


# ---------------------------------------------------------------------------
# finish_attempt — state machine
# ---------------------------------------------------------------------------


class TestFinishAttempt:
    def test_already_completed_raises(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid, status=Status.completed)
        uow = _make_uow()
        uow.trainer_attempts.get_by_id.return_value = attempt
        svc = _make_service(uow=uow)
        with pytest.raises(AttemptCompleted):
            svc.finish_attempt(42, student_guid)

    def test_attempt_not_found_raises(self):
        uow = _make_uow()
        uow.trainer_attempts.get_by_id.return_value = None
        svc = _make_service(uow=uow)
        with pytest.raises(TrainerAttemptNotExist):
            svc.finish_attempt(42, uuid4())

    def test_normal_flow_calls_cashback(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid, status=Status.in_progress)
        completed = _fake_attempt(
            student_guid=student_guid,
            status=Status.completed,
            questions=[],
            score=0,
        )
        uow = _make_uow()
        uow.trainer_attempts.get_by_id.return_value = attempt
        uow.trainer_attempts.finish_and_score.return_value = (completed, None)
        # _update_lesson_progress_from_trainer_attempt uses get_with_questions;
        # returning None triggers early return (wrapped in try/except anyway)
        uow.trainer_attempts.get_with_questions.return_value = None

        cashback = MagicMock()
        svc = _make_service(uow=uow, cashback=cashback)
        svc.finish_attempt(42, student_guid)

        cashback.check_and_update.assert_called_once_with(student_guid)

    def test_normal_flow_calls_finish_and_score(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid, status=Status.in_progress)
        completed = _fake_attempt(student_guid=student_guid, status=Status.completed, questions=[])
        uow = _make_uow()
        uow.trainer_attempts.get_by_id.return_value = attempt
        uow.trainer_attempts.finish_and_score.return_value = (completed, None)
        uow.trainer_attempts.get_with_questions.return_value = None
        svc = _make_service(uow=uow)
        svc.finish_attempt(42, student_guid)
        uow.trainer_attempts.finish_and_score.assert_called_once_with(42)

    def test_finish_commits(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid, status=Status.in_progress)
        completed = _fake_attempt(student_guid=student_guid, status=Status.completed, questions=[])
        uow = _make_uow()
        uow.trainer_attempts.get_by_id.return_value = attempt
        uow.trainer_attempts.finish_and_score.return_value = (completed, None)
        uow.trainer_attempts.get_with_questions.return_value = None
        svc = _make_service(uow=uow)
        svc.finish_attempt(42, student_guid)
        uow.commit.assert_called()


# ---------------------------------------------------------------------------
# get_attempt_result — access / status guards
# ---------------------------------------------------------------------------


class TestGetAttemptResult:
    def _make_cache_passthrough(self) -> MagicMock:
        cache = MagicMock()
        cache.get_or_set.side_effect = lambda key, fn, ttl: fn()
        return cache

    def test_not_found_raises(self):
        uow = _make_uow()
        uow.trainer_attempts.get_with_questions.return_value = None
        svc = _make_service(uow=uow, cache=self._make_cache_passthrough())
        with pytest.raises(TrainerAttemptNotExist):
            svc.get_attempt_result(99, uuid4())

    def test_wrong_student_raises_permission_error(self):
        owner = uuid4()
        other = uuid4()
        attempt = _fake_attempt(student_guid=owner, status=Status.completed, questions=[])
        uow = _make_uow()
        uow.trainer_attempts.get_with_questions.return_value = attempt
        svc = _make_service(uow=uow, cache=self._make_cache_passthrough())
        with pytest.raises(PermissionError):
            svc.get_attempt_result(attempt.id, other)

    def test_not_completed_raises(self):
        student_guid = uuid4()
        attempt = _fake_attempt(student_guid=student_guid, status=Status.in_progress, questions=[])
        uow = _make_uow()
        uow.trainer_attempts.get_with_questions.return_value = attempt
        svc = _make_service(uow=uow, cache=self._make_cache_passthrough())
        with pytest.raises(AttemptNotCompleted):
            svc.get_attempt_result(attempt.id, student_guid)

    def test_correct_student_completed_returns_dto(self):
        student_guid = uuid4()
        q = _fake_question(1, [10], [10], spend_time=20)
        attempt = _fake_attempt(student_guid=student_guid, status=Status.completed, questions=[q])
        uow = _make_uow()
        uow.trainer_attempts.get_with_questions.return_value = attempt
        svc = _make_service(uow=uow, cache=self._make_cache_passthrough())
        result = svc.get_attempt_result(attempt.id, student_guid)
        assert result.correct_answers == 1
        assert result.attempt_id == attempt.id
