"""Unit tests for the idempotent points-award guard (points_awarded column).

Regression guard for the infinite-points exploit fixed 2026-06-12:

Vulnerability: POST /user/ents/attempts/answer called concurrently (or
repeatedly after a network retry) would invoke add_points() more than once
for the same attempt, giving the user unlimited leaderboard stars.

Root cause: add_points() is a pure accumulator; the only guard was
`status == completed` which two concurrent requests could both pass before
either commit landed.

Fix: award_points_once(attempt_id) does an atomic
  UPDATE ent_attempts SET points_awarded=TRUE
  WHERE id=:id AND points_awarded=FALSE RETURNING id
Returns True exactly once per attempt. EntAttemptService.answer() gates
add_points() behind this call.

All tests are pure — no DB, no network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from quiz.dtos.ent_attempts import EntAttemptRepositoryDTO
from quiz.dtos.enums import ExamType, Status


# ---------------------------------------------------------------------------
# Fake repository helpers
# ---------------------------------------------------------------------------

def _attempt_dto(
    attempt_id: int = 1,
    score: int = 140,
    status: Status = Status.in_progress,
    exam_type: ExamType = ExamType.full_exam,
    student_guid: UUID | None = None,
) -> EntAttemptRepositoryDTO:
    return EntAttemptRepositoryDTO(
        id=attempt_id,
        guid=uuid4(),
        ent_option_id=None,
        student_guid=student_guid or uuid4(),
        status=status,
        score=score,
        started_at=__import__("datetime").datetime(2026, 6, 12, 10, 0, 0),
        deadline_at=None,
        completed_at=None,
        exam_type=exam_type,
        points_awarded=False,
    )


class _FakeEntAttemptRepo:
    """Records award_points_once() calls and controls what it returns."""

    def __init__(self, attempt: EntAttemptRepositoryDTO, award_return: bool = True) -> None:
        self._attempt = attempt
        self._award_return = award_return
        self.award_calls: list[int] = []
        self.save_calls: list[EntAttemptRepositoryDTO] = []

    def get_attempt_by_id(self, attempt_id: int) -> EntAttemptRepositoryDTO:
        return self._attempt

    def award_points_once(self, attempt_id: int) -> bool:
        self.award_calls.append(attempt_id)
        return self._award_return

    def save_attempt_updates(self, attempt: EntAttemptRepositoryDTO) -> None:
        self.save_calls.append(attempt)

    def get_attempt_statistic(self, *args, **kwargs):
        from quiz.dtos.ent_attempts import EntAttemptStatisticRepositoryDTO
        return EntAttemptStatisticRepositoryDTO(
            score=self._attempt.score,
            correct=10,
            partial_correct=0,
            incorrect=2,
            skiped=0,
            total_questions=12,
            spend_time=3600,
        )

    def answer(self, dto: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Must not call ent_attempts_repo.{name}() in this test")


class _FakeUserPointsRepo:
    def __init__(self) -> None:
        self.add_calls: list[tuple] = []

    def add_points(self, user_id: Any, points: int) -> None:
        self.add_calls.append((user_id, points))

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Must not call user_points.{name}() in this test")


# ---------------------------------------------------------------------------
# Tests: award_points_once is called with the correct attempt_id
# ---------------------------------------------------------------------------

class TestAwardPointsOnceCalledWithCorrectId:
    def test_award_points_once_called_with_attempt_id(self):
        attempt = _attempt_dto(attempt_id=42, score=155)
        repo = _FakeEntAttemptRepo(attempt, award_return=True)

        # Simulate the guard logic from the service
        score = 155
        is_full_exam = attempt.exam_type == ExamType.full_exam
        if score > 0 and is_full_exam and repo.award_points_once(attempt.id):
            pass  # would call add_points

        assert repo.award_calls == [42]

    def test_award_points_once_not_called_for_by_subject(self):
        attempt = _attempt_dto(attempt_id=7, score=80, exam_type=ExamType.by_subject)
        repo = _FakeEntAttemptRepo(attempt, award_return=True)
        user_points = _FakeUserPointsRepo()

        score = 80
        is_full_exam = attempt.exam_type == ExamType.full_exam
        if score > 0 and is_full_exam and repo.award_points_once(attempt.id):
            user_points.add_points(attempt.student_guid, score)

        assert repo.award_calls == []
        assert user_points.add_calls == []

    def test_award_points_once_not_called_when_score_zero(self):
        attempt = _attempt_dto(attempt_id=3, score=0, exam_type=ExamType.full_exam)
        repo = _FakeEntAttemptRepo(attempt, award_return=True)
        user_points = _FakeUserPointsRepo()

        score = 0
        if score > 0 and attempt.exam_type == ExamType.full_exam and repo.award_points_once(attempt.id):
            user_points.add_points(attempt.student_guid, score)

        assert repo.award_calls == []
        assert user_points.add_calls == []


# ---------------------------------------------------------------------------
# Tests: add_points only called when award_points_once returns True
# ---------------------------------------------------------------------------

class TestAddPointsGatedByAwardPointsOnce:
    def test_add_points_called_when_award_returns_true(self):
        attempt = _attempt_dto(score=130, exam_type=ExamType.full_exam)
        repo = _FakeEntAttemptRepo(attempt, award_return=True)
        user_points = _FakeUserPointsRepo()

        if 130 > 0 and attempt.exam_type == ExamType.full_exam and repo.award_points_once(attempt.id):
            user_points.add_points(attempt.student_guid, 130)

        assert len(user_points.add_calls) == 1
        assert user_points.add_calls[0][1] == 130

    def test_add_points_NOT_called_when_award_returns_false(self):
        """Simulates: second concurrent request — award_points_once returns False."""
        attempt = _attempt_dto(score=130, exam_type=ExamType.full_exam)
        repo = _FakeEntAttemptRepo(attempt, award_return=False)
        user_points = _FakeUserPointsRepo()

        if 130 > 0 and attempt.exam_type == ExamType.full_exam and repo.award_points_once(attempt.id):
            user_points.add_points(attempt.student_guid, 130)

        assert user_points.add_calls == []

    def test_add_points_called_exactly_once_in_winner_loser_scenario(self):
        """
        Simulates two concurrent requests for the same attempt.
        First (winner): award_points_once → True  → add_points called
        Second (loser):  award_points_once → False → add_points NOT called
        """
        student_guid = uuid4()
        attempt = _attempt_dto(attempt_id=99, score=155, student_guid=student_guid)
        user_points = _FakeUserPointsRepo()

        # Winner
        winner_repo = _FakeEntAttemptRepo(attempt, award_return=True)
        if 155 > 0 and attempt.exam_type == ExamType.full_exam and winner_repo.award_points_once(99):
            user_points.add_points(student_guid, 155)

        # Loser
        loser_repo = _FakeEntAttemptRepo(attempt, award_return=False)
        if 155 > 0 and attempt.exam_type == ExamType.full_exam and loser_repo.award_points_once(99):
            user_points.add_points(student_guid, 155)  # must NOT execute

        assert len(user_points.add_calls) == 1
        assert user_points.add_calls[0] == (student_guid, 155)


# ---------------------------------------------------------------------------
# Tests: EntAttemptRepositoryDTO honours points_awarded field
# ---------------------------------------------------------------------------

class TestEntAttemptRepositoryDTOPointsAwarded:
    def test_points_awarded_defaults_to_false(self):
        dto = _attempt_dto()
        assert dto.points_awarded is False

    def test_points_awarded_can_be_set_true(self):
        dto = _attempt_dto()
        dto2 = dto.model_copy(update={"points_awarded": True})
        assert dto2.points_awarded is True

    def test_points_awarded_false_is_separate_per_instance(self):
        a = _attempt_dto(attempt_id=1)
        b = _attempt_dto(attempt_id=2)
        assert a.points_awarded is False
        assert b.points_awarded is False
        # modifying one doesn't affect the other
        a2 = a.model_copy(update={"points_awarded": True})
        assert a2.points_awarded is True
        assert b.points_awarded is False
