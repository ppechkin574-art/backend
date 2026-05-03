import logging
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from quiz.uows.uows import UnitOfWorkTests

logger = logging.getLogger(__name__)


class ProgressRecorder:
    @staticmethod
    def record_attempt_progress(
        uow: "UnitOfWorkTests",
        user_id: UUID,
        question_id: int,
        is_correct: bool,
        attempt_type: str,
        attempt_id: int,
    ) -> None:
        """Record progress for attempt"""

        try:
            if hasattr(uow, "progress"):
                uow.progress.record_progress(
                    user_id=str(user_id),
                    question_id=question_id,
                    is_correct=is_correct,
                    attempt_type=attempt_type,
                    attempt_id=attempt_id,
                )
                logger.info(
                    "Recorded progress for question %s, is_correct=%s, type=%s, attempt=%s",
                    question_id,
                    is_correct,
                    attempt_type,
                    attempt_id,
                )
            else:
                logger.warning("UOW has no progress recorder for attempt type %s", attempt_type)
        except Exception as e:
            logger.exception("Failed to record progress: %s", e)

    # @staticmethod
    # def record_batch_progress(
    #     uow: "UnitOfWorkTests",
    #     user_id: UUID,
    #     questions_data: list,
    #     attempt_type: str,
    #     attempt_id: int,
    # ) -> None:
    #     """Record progress for batch of attempts"""

    #     recorded = 0
    #     failed = 0

    #     for question_data in questions_data:
    #         try:
    #             ProgressRecorder.record_attempt_progress(
    #                 uow=uow,
    #                 user_id=user_id,
    #                 question_id=question_data["question_id"],
    #                 is_correct=question_data["is_correct"],
    #                 attempt_type=attempt_type,
    #                 attempt_id=attempt_id,
    #                 metadata=question_data.get("metadata"),
    #             )
    #             recorded += 1
    #         except Exception as e:
    #             logger.exception(
    #                 "Failed to record progress for question %s: %s",
    #                 question_data.get("question_id"),
    #                 e,
    #             )
    #             failed += 1

    #     logger.info("Progress recording completed: %s recorded, %s failed", recorded, failed)
