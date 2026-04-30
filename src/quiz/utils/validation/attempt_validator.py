import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from quiz.dtos.enums import Status
from quiz.exceptions import (
    AttemptCompleted,
    TestQuestionNotExist,
    TrainerAttemptNotExist,
    WrongStudent,
)

logger = logging.getLogger(__name__)


class AttemptValidator:
    """Валидатор для проверок попыток тестов"""

    @staticmethod
    def validate_attempt_exists(attempt, attempt_id: int, student_guid: UUID) -> None:
        """Проверка существования попытки и принадлежности студенту"""
        if not attempt:
            raise TrainerAttemptNotExist(f"Attempt {attempt_id} not found")

        if str(attempt.student_guid) != str(student_guid):
            logger.exception(
                "Student mismatch! Attempt belongs to %s, but request from %s",
                attempt.student_guid,
                student_guid,
            )
            raise WrongStudent("Attempt doesn't belong to student")

    @staticmethod
    def validate_attempt_not_completed(attempt) -> None:
        """Проверка что попытка не завершена"""
        if attempt.status != Status.in_progress:
            raise AttemptCompleted("Cannot answer - attempt already completed")

    @staticmethod
    def validate_deadline(deadline: datetime, current_time: datetime) -> bool:
        """Проверка дедлайна"""
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)

        deadline_exceeded = current_time > deadline
        if deadline_exceeded:
            exceeded_seconds = (current_time - deadline).total_seconds()
            logger.warning("Attempt exceeded deadline by %s seconds", exceeded_seconds)

        return deadline_exceeded

    @staticmethod
    def validate_question_belongs_to_attempt(
        question_id: int,
        allowed_question_ids: set[int],
        get_question_func: Callable | None = None,
    ) -> None:
        """Проверка что вопрос принадлежит попытке"""
        if question_id not in allowed_question_ids:
            if get_question_func:
                question = get_question_func(question_id)
                if not question:
                    raise TestQuestionNotExist(f"Question {question_id} does not belong to this attempt")
            else:
                raise TestQuestionNotExist(f"Question {question_id} does not belong to this attempt")
