"""Unit tests for EntAttemptService.

Covers:
- Constants: ENT_BY_SUBJECT_DURATION (3600s), ENT_FULL_EXAM_DURATION (14400s)
- answer: attempt not found (TrainerAttemptNotExist), wrong student (WrongStudent),
  already completed (AlreadyAnswered)
- update_current_question_index: ownership guard (WrongStudent), not found
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import payments.models  # noqa: F401 — ORM mapper registration
import pytest
import quiz.models  # noqa: F401
import student.models  # noqa: F401
import subscription.models  # noqa: F401

from quiz.dtos.ent_answers import EntAttemptAnswerServiceDTO
from quiz.dtos.enums import ExamType, Status
from quiz.exceptions import AlreadyAnswered, TrainerAttemptNotExist, WrongStudent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__enter__ = lambda s: s
    uow.__exit__ = MagicMock(return_value=False)
    return uow


def _make_service(uow=None, cache=None, cashback=None):
    from quiz.services.ent_attempts import EntAttemptService

    return EntAttemptService(
        uow=uow or _make_uow(),
        cache_service=cache or MagicMock(),
        cashback_service=cashback or MagicMock(),
    )


def _fake_ent_attempt(
    student_guid=None,
    status: Status = Status.in_progress,
    exam_type: ExamType = ExamType.by_subject,
    ent_option_id: int = 1,
):
    from datetime import datetime, timedelta

    started = datetime(2026, 6, 1, 10, 0, 0)
    return SimpleNamespace(
        id=1,
        student_guid=student_guid or uuid4(),
        status=status,
        exam_type=exam_type,
        ent_option_id=ent_option_id,
        started_at=started,
        deadline_at=started + timedelta(hours=1),
        completed_at=None,
        score=0,
        full_exam_question_ids=None,
        subject_combination_id=None,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_by_subject_duration_is_3600():
    from quiz.services.ent_attempts import EntAttemptService

    assert EntAttemptService.ENT_BY_SUBJECT_DURATION == 60 * 60


def test_full_exam_duration_is_14400():
    from quiz.services.ent_attempts import EntAttemptService

    assert EntAttemptService.ENT_FULL_EXAM_DURATION == 240 * 60


# ---------------------------------------------------------------------------
# answer — guard clauses
# ---------------------------------------------------------------------------


class TestAnswerGuards:
    def _make_answer(self, student_guid=None, attempt_id: int = 1):
        return EntAttemptAnswerServiceDTO(
            student_guid=student_guid or uuid4(),
            ent_attempt_id=attempt_id,
            questions=[],
        )

    def test_attempt_not_found_raises(self):
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = None
        svc = _make_service(uow=uow)
        with pytest.raises(TrainerAttemptNotExist):
            svc.answer(self._make_answer())

    def test_wrong_student_raises(self):
        owner = uuid4()
        requester = uuid4()
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = _fake_ent_attempt(
            student_guid=owner
        )
        svc = _make_service(uow=uow)
        with pytest.raises(WrongStudent):
            svc.answer(self._make_answer(student_guid=requester))

    def test_already_completed_raises(self):
        student_guid = uuid4()
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = _fake_ent_attempt(
            student_guid=student_guid, status=Status.completed
        )
        svc = _make_service(uow=uow)
        with pytest.raises(AlreadyAnswered):
            svc.answer(self._make_answer(student_guid=student_guid))


# ---------------------------------------------------------------------------
# update_current_question_index — ownership guard
# ---------------------------------------------------------------------------


class TestUpdateCurrentQuestionIndex:
    def test_attempt_not_found_raises(self):
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = None
        svc = _make_service(uow=uow)
        with pytest.raises(TrainerAttemptNotExist):
            svc.update_current_question_index(1, uuid4(), 5)

    def test_wrong_student_raises(self):
        owner = uuid4()
        other = uuid4()
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = _fake_ent_attempt(
            student_guid=owner
        )
        svc = _make_service(uow=uow)
        with pytest.raises(WrongStudent):
            svc.update_current_question_index(1, other, 5)

    def test_valid_owner_updates_index(self):
        student_guid = uuid4()
        attempt = _fake_ent_attempt(student_guid=student_guid)
        uow = _make_uow()
        uow.ent_attempts.get_attempt_by_id.return_value = attempt
        svc = _make_service(uow=uow)
        result = svc.update_current_question_index(1, student_guid, 7)
        uow.ent_attempts.save_attempt_updates.assert_called_once_with(attempt)
        assert result["current_question_index"] == 7
        assert result["status"] == "success"
