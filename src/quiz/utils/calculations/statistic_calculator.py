# import logging
# from collections.abc import Callable
# from datetime import date, datetime, timedelta
# from typing import Any

# from quiz.utils.calculations.math_utils import MathUtils
# from quiz.utils.time.time_normalizer import TimeNormalizerService

# logger = logging.getLogger(__name__)


# class StatisticsCalculator:
#     # @staticmethod
#     # def calculate_attempts_statistics(
#     #     attempts: list,
#     #     get_attempt_stats_func: Callable,
#     #     get_question_times_func: Callable | None = None,
#     #     exam_type: str = "trainer",
#     #     timezone_offset_hours: int = 0,
#     # ) -> dict[str, Any]:
#     #     """Calculate attempts statistics"""
#     #     daily_stats = {}
#     #     all_attempt_stats = []
#     #     all_question_times = []
#     #     total_active_seconds = 0
#     #     total_session_seconds = 0

#     #     for attempt in attempts:
#     #         attempt_stats = get_attempt_stats_func(attempt.id)

#     #         question_times = []
#     #         if get_question_times_func:
#     #             question_times = get_question_times_func(attempt.id)

#     #         time_metrics = StatisticsCalculator._calculate_time_metrics(
#     #             attempt=attempt,
#     #             attempt_stats=attempt_stats,
#     #             question_times=question_times,
#     #             exam_type=exam_type,
#     #             timezone_offset_hours=timezone_offset_hours,
#     #         )

#     #         total_active_seconds += time_metrics["active_seconds"]
#     #         total_session_seconds += time_metrics["session_seconds"]
#     #         all_question_times.extend(time_metrics["question_times"])

#     #         attempt_stat = {
#     #             "attempt_id": attempt.id,
#     #             "completed_at": attempt.completed_at,
#     #             "correct_answers": attempt_stats.get("correct", 0),
#     #             "partial_correct_answers": attempt_stats.get("partial_correct", 0),
#     #             "total_questions": attempt_stats.get("total_questions", 0),
#     #             "spend_time": attempt_stats.get("spend_time", 0),
#     #             "score": attempt_stats.get(
#     #                 "score", attempt.score if hasattr(attempt, "score") else 0
#     #             ),
#     #             "time_correction_applied": time_metrics["is_time_corrected"],
#     #             "correct_percentage": MathUtils.calculate_percentage(
#     #                 attempt_stats.get("correct", 0),
#     #                 attempt_stats.get("total_questions", 1),
#     #             ),
#     #             "avg_time_per_question": (
#     #                 attempt_stats.get("spend_time", 0)
#     #                 / attempt_stats.get("total_questions", 1)
#     #                 if attempt_stats.get("total_questions", 0) > 0
#     #                 else 0
#     #             ),
#     #         }

#     #         if hasattr(attempt, "trainer") and attempt.trainer:
#     #             attempt_stat["trainer_name"] = attempt.trainer.name
#     #         if hasattr(attempt, "options") and attempt.options:
#     #             attempt_stat["option_number"] = attempt.options.option_number
#     #         if hasattr(attempt, "subject") and attempt.subject:
#     #             attempt_stat["subject_name"] = attempt.subject.name

#     #         all_attempt_stats.append(attempt_stat)

#     #         attempt_date = StatisticsCalculator._get_local_date(
#     #             attempt.completed_at or attempt.started_at, timezone_offset_hours
#     #         )

#     #         if attempt_date not in daily_stats:
#     #             daily_stats[attempt_date] = []
#     #         daily_stats[attempt_date].append(attempt_stat)

#     #     return {
#     #         "daily_stats": daily_stats,
#     #         "all_attempt_stats": all_attempt_stats,
#     #         "all_question_times": all_question_times,
#     #         "total_active_seconds": total_active_seconds,
#     #         "total_session_seconds": total_session_seconds,
#     #     }

#     # @staticmethod
#     # def _calculate_time_metrics(
#     #     attempt: Any,
#     #     attempt_stats: dict[str, Any],
#     #     question_times: list[float],
#     #     exam_type: str,
#     # ) -> dict[str, Any]:
#     #     """Calculate time metrics for attempt"""
#     #     if attempt.completed_at and attempt.started_at:
#     #         session_seconds = int(
#     #             (attempt.completed_at - attempt.started_at).total_seconds()
#     #         )

#     #         if exam_type == "trainer":
#     #             time_metrics = TimeNormalizerService.normalize_trainer_time(
#     #                 question_times=question_times,
#     #                 total_session_seconds=session_seconds,
#     #             )
#     #             active_seconds = time_metrics["active_seconds"] or session_seconds
#     #         elif exam_type.startswith("ent_"):
#     #             time_metrics = TimeNormalizerService.normalize_ent_time(
#     #                 start_time=attempt.started_at,
#     #                 end_time=attempt.completed_at,
#     #                 exam_type=exam_type.replace("ent_", ""),
#     #             )
#     #             active_seconds = time_metrics["corrected_session_seconds"]
#     #         else:
#     #             active_seconds = session_seconds
#     #             time_metrics = {
#     #                 "active_seconds": active_seconds,
#     #                 "is_time_corrected": False,
#     #                 "question_times": question_times,
#     #             }
#     #     else:
#     #         active_seconds = attempt_stats.get("spend_time", 0)
#     #         session_seconds = active_seconds
#     #         time_metrics = {
#     #             "active_seconds": active_seconds,
#     #             "is_time_corrected": False,
#     #             "question_times": question_times,
#     #         }

#     #     return {
#     #         "active_seconds": active_seconds,
#     #         "session_seconds": session_seconds,
#     #         "is_time_corrected": time_metrics.get("is_time_corrected", False),
#     #         "question_times": time_metrics.get("question_times", question_times),
#     #     }

#     # @staticmethod
#     # def _get_local_date(dt: datetime, timezone_offset_hours: int) -> date:
#     #     """Get date in local time"""
#     #     if dt:
#     #         local_dt = dt + timedelta(hours=timezone_offset_hours)
#     #         return local_dt.date()
#     #     return date.today()

#     # @staticmethod
#     # def calculate_overall_statistics(
#     #     statistics: dict[str, Any], include_partial: bool = True
#     # ) -> dict[str, Any]:
#     #     """Calculate overall statistics"""
#     #     all_attempt_stats = statistics["all_attempt_stats"]
#     #     total_active_seconds = statistics["total_active_seconds"]
#     #     all_question_times = statistics["all_question_times"]

#     #     if not all_attempt_stats:
#     #         return StatisticsCalculator._get_empty_statistics()

#     #     total_attempts = len(all_attempt_stats)
#     #     total_correct_answers = sum(a["correct_answers"] for a in all_attempt_stats)
#     #     total_partial_correct_answers = sum(
#     #         a.get("partial_correct_answers", 0) for a in all_attempt_stats
#     #     )
#     #     total_questions = sum(a["total_questions"] for a in all_attempt_stats)

#     #     avg_correct_percentage = (
#     #         (sum(a["correct_percentage"] for a in all_attempt_stats) / total_attempts)
#     #         if total_attempts > 0
#     #         else 0
#     #     )

#     #     overall_avg_time_per_question = (
#     #         (total_active_seconds / total_questions) if total_questions > 0 else 0
#     #     )

#     #     overall_median_time_per_question = MathUtils.calculate_median(
#     #         all_question_times
#     #     )

#     #     avg_score = (
#     #         (sum(a["score"] for a in all_attempt_stats) / total_attempts)
#     #         if total_attempts > 0
#     #         else 0
#     #     )

#     #     avg_spend_time = (
#     #         (total_active_seconds / total_attempts) if total_attempts > 0 else 0
#     #     )

#     #     efficiency_ratio = (
#     #         total_active_seconds / statistics["total_session_seconds"]
#     #         if statistics["total_session_seconds"] > 0
#     #         else None
#     #     )

#     #     result = {
#     #         "total_attempts": total_attempts,
#     #         "total_correct_answers": total_correct_answers,
#     #         "total_questions": total_questions,
#     #         "total_spend_time": total_active_seconds,
#     #         "avg_correct_percentage": avg_correct_percentage,
#     #         "overall_avg_time_per_question": overall_avg_time_per_question,
#     #         "median_time_per_question": overall_median_time_per_question,
#     #         "avg_score": avg_score,
#     #         "avg_spend_time": avg_spend_time,
#     #         "efficiency_ratio": efficiency_ratio,
#     #     }

#     #     if include_partial:
#     #         result["total_partial_correct_answers"] = total_partial_correct_answers

#     #     return result

#     # @staticmethod
#     # def _get_empty_statistics() -> dict[str, Any]:
#     #     """Get empty statistics"""
#     #     return {
#     #         "total_attempts": 0,
#     #         "total_correct_answers": 0,
#     #         "total_partial_correct_answers": 0,
#     #         "total_questions": 0,
#     #         "total_spend_time": 0,
#     #         "avg_correct_percentage": 0.0,
#     #         "overall_avg_time_per_question": 0.0,
#     #         "median_time_per_question": 0.0,
#     #         "avg_score": 0.0,
#     #         "avg_spend_time": 0.0,
#     #         "efficiency_ratio": None,
#     #     }

#     # @staticmethod
#     # def calculate_daily_statistics(
#     #     daily_stats: dict[date, list[dict]], include_partial: bool = True
#     # ) -> list[dict]:
#     #     """Calculate daily statistics"""
#     #     daily_results = []

#     #     for date_key, date_attempts in sorted(daily_stats.items()):
#     #         day_total_attempts = len(date_attempts)
#     #         day_total_correct_answers = sum(a["correct_answers"] for a in date_attempts)
#     #         day_total_partial_correct_answers = sum(
#     #             a.get("partial_correct_answers", 0) for a in date_attempts
#     #         )
#     #         day_total_questions = sum(a["total_questions"] for a in date_attempts)
#     #         day_total_spend_time = sum(a["spend_time"] for a in date_attempts)

#     #         day_avg_correct_percentage = (
#     #             (
#     #                 sum(a["correct_percentage"] for a in date_attempts)
#     #                 / day_total_attempts
#     #             )
#     #             if day_total_attempts > 0
#     #             else 0
#     #         )

#     #         day_overall_avg_time_per_question = (
#     #             (day_total_spend_time / day_total_questions)
#     #             if day_total_questions > 0
#     #             else 0
#     #         )

#     #         day_times_per_question = [
#     #             a["avg_time_per_question"]
#     #             for a in date_attempts
#     #             if a["avg_time_per_question"] > 0
#     #         ]
#     #         day_median_time_per_question = MathUtils.calculate_median(
#     #             day_times_per_question
#     #         )

#     #         day_avg_score = (
#     #             (sum(a["score"] for a in date_attempts) / day_total_attempts)
#     #             if day_total_attempts > 0
#     #             else 0
#     #         )

#     #         day_avg_spend_time = (
#     #             (day_total_spend_time / day_total_attempts)
#     #             if day_total_attempts > 0
#     #             else 0
#     #         )

#     #         day_stat = {
#     #             "date": date_key,
#     #             "total_attempts": day_total_attempts,
#     #             "total_correct_answers": day_total_correct_answers,
#     #             "total_questions": day_total_questions,
#     #             "total_spend_time": day_total_spend_time,
#     #             "avg_correct_percentage": day_avg_correct_percentage,
#     #             "overall_avg_time_per_question": day_overall_avg_time_per_question,
#     #             "median_time_per_question": day_median_time_per_question,
#     #             "avg_score": day_avg_score,
#     #             "avg_spend_time": day_avg_spend_time,
#     #         }

#     #         if include_partial:
#     #             day_stat["total_partial_correct_answers"] = (
#     #                 day_total_partial_correct_answers
#     #             )

#     #         daily_results.append(day_stat)

#     #     return daily_results

#     # @staticmethod
#     # def calculate_aggregated_statistics(
#     #     attempts_data: list[dict[str, Any]],
#     #     group_by_field: str,
#     #     include_accuracy: bool = True,
#     # ) -> dict[Any, dict[str, Any]]:
#     #     """Calculate aggregated statistics"""
#     #     aggregated = {}

#     #     for data in attempts_data:
#     #         key = data.get(group_by_field)
#     #         if key is None:
#     #             continue

#     #         if key not in aggregated:
#     #             aggregated[key] = {
#     #                 group_by_field: key,
#     #                 "name": data.get(f"{group_by_field.split('_')[0]}_name", ""),
#     #                 "total_questions": 0,
#     #                 "correct_answers": 0,
#     #                 "partial_correct_answers": 0,
#     #             }

#     #         aggregated[key]["total_questions"] += data.get("total_questions", 0)
#     #         aggregated[key]["correct_answers"] += data.get("correct_answers", 0)
#     #         aggregated[key]["partial_correct_answers"] += data.get("partial_correct_answers", 0)

#     #     if include_accuracy:
#     #         for _key, stats in aggregated.items():
#     #             stats["accuracy"] = MathUtils.calculate_accuracy(stats["correct_answers"], stats["total_questions"])

#     #     return aggregated
