import logging
from datetime import UTC, datetime
from typing import Any

from quiz.utils.time.date_utils import DateUtils

logger = logging.getLogger(__name__)


class TimeNormalizerService:
    """Service for time normalization"""

    MAX_REASONABLE_HOURS = {
        "ent_full_exam": 6,  # max 6 hours for full exam
        "ent_subject": 2,  # max 2 hours for ent by subject
        "trainer": 3,  # max 3 hours for trainer
        "daily": 2,  # max 2 hours for daily test
    }

    UNREALISTIC_MULTIPLIER = 2.0  # if time > limit * UNREALISTIC_MULTIPLIER
    CORRECTION_MULTIPLIER = 1.5  # if time > limit

    @staticmethod
    def normalize_ent_time(start_time: datetime, end_time: datetime, exam_type: str = "by_subject") -> dict[str, Any]:
        """Normalize ent time"""
        start_time = DateUtils.ensure_timezone(start_time, UTC)
        end_time = DateUtils.ensure_timezone(end_time, UTC)
        total_seconds = int((end_time - start_time).total_seconds())

        if exam_type == "full_exam":
            limit_hours = TimeNormalizerService.MAX_REASONABLE_HOURS["ent_full_exam"]
        else:
            limit_hours = TimeNormalizerService.MAX_REASONABLE_HOURS["ent_subject"]

        limit_seconds = limit_hours * 3600
        max_unrealistic_seconds = limit_seconds * TimeNormalizerService.UNREALISTIC_MULTIPLIER

        is_corrected = False
        correction_reason = None
        corrected_seconds = total_seconds

        if total_seconds > max_unrealistic_seconds:
            corrected_seconds = int(limit_seconds * TimeNormalizerService.CORRECTION_MULTIPLIER)
            is_corrected = True
            correction_reason = f"unrealistic time: ({total_seconds}s > {max_unrealistic_seconds}s)"

            logger.warning(
                "ENT time corrected: %ss -> %ss. Reason: %s",
                total_seconds,
                corrected_seconds,
                correction_reason,
            )
        elif total_seconds > limit_seconds:
            corrected_seconds = total_seconds
            logger.info(
                "ENT time slightly above limit: %ss > %ss (%s)",
                total_seconds,
                limit_seconds,
                exam_type,
            )

        return {
            "total_session_seconds": total_seconds,
            "corrected_session_seconds": corrected_seconds,
            "is_time_corrected": is_corrected,
            "correction_reason": correction_reason,
            "limit_seconds": limit_seconds,
        }

    # @staticmethod
    # def normalize_trainer_time(
    #     question_times: list[int],  # time for each question
    #     total_session_seconds: int,  # total session time
    # ) -> dict[str, Any]:
    #     """Normalize trainer time"""
    #     MAX_TIME_PER_QUESTION = 30 * 60  # 30 minutes for each question

    #     corrected_question_times = []
    #     for time in question_times:
    #         if time > MAX_TIME_PER_QUESTION:
    #             corrected_time = MAX_TIME_PER_QUESTION
    #             logger.warning(
    #                 "Question time corrected: %ss -> %ss", time, corrected_time
    #             )
    #         else:
    #             corrected_time = time
    #         corrected_question_times.append(corrected_time)

    #     active_seconds = sum(corrected_question_times)

    #     limit_hours = TimeNormalizerService.MAX_REASONABLE_HOURS["trainer"]
    #     limit_seconds = limit_hours * 3600
    #     max_unrealistic_seconds = (
    #         limit_seconds * TimeNormalizerService.UNREALISTIC_MULTIPLIER
    #     )

    #     is_corrected = False
    #     correction_reason = None
    #     corrected_session_seconds = total_session_seconds

    #     if total_session_seconds > max_unrealistic_seconds:
    #         corrected_session_seconds = min(
    #             int(limit_seconds * TimeNormalizerService.CORRECTION_MULTIPLIER),
    #             active_seconds * 2,
    #         )
    #         is_corrected = True
    #         correction_reason = "Total time is unrealistically long"

    #     efficiency_ratio = None
    #     if total_session_seconds > 0:
    #         efficiency_ratio = active_seconds / total_session_seconds

    #     return {
    #         "total_session_seconds": total_session_seconds,
    #         "corrected_session_seconds": corrected_session_seconds,
    #         "active_seconds": active_seconds,
    #         "efficiency_ratio": efficiency_ratio,
    #         "is_time_corrected": is_corrected,
    #         "correction_reason": correction_reason,
    #         "question_times": corrected_question_times,
    #     }

    @staticmethod
    def normalize_and_validate_time(
        start_time: datetime,
        end_time: datetime,
        exam_type: str,
        max_allowed_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Normalize and validate time"""
        start_time = DateUtils.ensure_timezone(start_time, UTC)
        end_time = DateUtils.ensure_timezone(end_time, UTC)
        time_metrics = TimeNormalizerService.normalize_ent_time(
            start_time=start_time,
            end_time=end_time,
            exam_type=exam_type,
        )

        corrected_seconds = time_metrics["corrected_session_seconds"]

        if max_allowed_seconds and corrected_seconds > max_allowed_seconds:
            logger.warning("Time exceeded limit: %ss > %ss", corrected_seconds, max_allowed_seconds)
            time_metrics["exceeded_limit"] = True
            time_metrics["exceeded_by_seconds"] = corrected_seconds - max_allowed_seconds
        else:
            time_metrics["exceeded_limit"] = False
            time_metrics["exceeded_by_seconds"] = 0

        return time_metrics

    # @staticmethod
    # def calculate_time_metrics(
    #     start_time: datetime,
    #     end_time: datetime,
    #     question_times: list[float],
    #     exam_type: str = "trainer",
    # ) -> dict[str, Any]:
    #     """Calculate time metrics"""
    #     start_time = DateUtils.ensure_timezone(start_time, UTC)
    #     end_time = DateUtils.ensure_timezone(end_time, UTC)
    #     session_seconds = int((end_time - start_time).total_seconds())

    #     if exam_type == "trainer":
    #         time_metrics = TimeNormalizerService.normalize_trainer_time(
    #             question_times=question_times,
    #             total_session_seconds=session_seconds,
    #         )
    #     else:
    #         time_metrics = TimeNormalizerService.normalize_ent_time(
    #             start_time=start_time,
    #             end_time=end_time,
    #             exam_type=exam_type,
    #         )

    #     if question_times:
    #         avg_question_time = sum(question_times) / len(question_times)
    #         max_question_time = max(question_times)
    #         min_question_time = min(question_times)
    #     else:
    #         avg_question_time = max_question_time = min_question_time = 0

    #     time_metrics.update(
    #         {
    #             "session_seconds": session_seconds,
    #             "avg_question_time": avg_question_time,
    #             "max_question_time": max_question_time,
    #             "min_question_time": min_question_time,
    #             "questions_count": len(question_times),
    #         }
    #     )

    #     return time_metrics

    @staticmethod
    def cap_question_time(spend_time: int, max_time_per_question: int = 1800) -> int:
        """Limit question time"""
        if spend_time > max_time_per_question:
            logger.warning(
                "Question time too long: %ss > %ss. Capped to %ss",
                spend_time,
                max_time_per_question,
                max_time_per_question,
            )
            return max_time_per_question
        return spend_time
