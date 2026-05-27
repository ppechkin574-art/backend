import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from analytics.service import AnalyticService
from quiz.dtos.enums import ExamType
from quiz.dtos.statistic import (
    DailyStatisticSummaryDTO,
    EntStatisticSummaryDTO,
    StatisticRequestDTO,
    SubjectProgressDTO,
    TopicProgressDTO,
    TrainerStatisticSummaryDTO,
)
from quiz.uows.uows import UnitOfWorkTests
from quiz.utils.calculations.init import MathUtils, StreakCalculator
from quiz.utils.period.init import (
    PeriodCalculator,
    kz_day_window_utc,
    to_kz_date,
)
from quiz.utils.validation.init import StatisticValidator
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class StatisticService:
    def __init__(
        self,
        uow: UnitOfWorkTests,
        analytic_service: AnalyticService,
        cache_service: CacheService,
    ):
        self.uow = uow
        self.analytic_service = analytic_service
        self._cache_service = cache_service

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="enhanced_global_statistic")
    def get_enhanced_global_statistic(
        self,
        student_id: UUID,
        request: StatisticRequestDTO,
    ) -> dict[str, Any]:
        start_date, end_date, description = PeriodCalculator.calculate_period_dates(request)

        # start_date/end_date are KZ-local dates (see today_kz in
        # period_calculator). Translate the inclusive [start_kz 00:00,
        # end_kz 23:59] window into the equivalent UTC range so DB
        # queries against naive-UTC `completed_at` columns return all
        # rows the user thinks belong to the period.
        start_datetime, end_datetime = kz_day_window_utc(start_date, end_date)
        period_days = PeriodCalculator.get_period_days(start_datetime, end_datetime)

        with self.uow:
            period_ent_subject = self._get_period_ent_statistic(
                student_id, start_datetime, end_datetime, ExamType.by_subject
            )
            overall_ent_subject = self._get_overall_ent_statistic(student_id, ExamType.by_subject)

            period_ent_full = self._get_period_ent_statistic(
                student_id, start_datetime, end_datetime, ExamType.full_exam
            )
            overall_ent_full = self._get_overall_ent_statistic(student_id, ExamType.full_exam)

            period_trainer = self._get_period_trainer_statistic(student_id, start_datetime, end_datetime)
            period_daily = self._get_period_daily_statistic(student_id, start_datetime, end_datetime)

            overall_trainer = self._get_overall_trainer_statistic(student_id)
            overall_daily = self._get_overall_daily_statistic(student_id)

            ent_subject_dates = self._get_completed_dates_for_ent(
                student_id, start_datetime, end_datetime, ExamType.by_subject
            )
            ent_full_dates = self._get_completed_dates_for_ent(
                student_id, start_datetime, end_datetime, ExamType.full_exam
            )
            trainer_dates = self._get_completed_dates_for_trainer(student_id, start_datetime, end_datetime)
            daily_dates = self._get_completed_dates_for_daily(student_id, start_datetime, end_datetime)

            all_dates = ent_subject_dates | ent_full_dates | trainer_dates | daily_dates

            current_streak = StreakCalculator.calculate_streak_on_date(all_dates, end_date, include_target_date=True)

            max_streak_in_period = StreakCalculator.calculate_max_streak_in_period(all_dates, start_date, end_date)
            ent_subject_max_streak = StreakCalculator.calculate_max_streak_in_period(
                ent_subject_dates, start_date, end_date
            )
            ent_full_max_streak = StreakCalculator.calculate_max_streak_in_period(ent_full_dates, start_date, end_date)
            trainer_max_streak = StreakCalculator.calculate_max_streak_in_period(trainer_dates, start_date, end_date)
            daily_max_streak = StreakCalculator.calculate_max_streak_in_period(daily_dates, start_date, end_date)

            _, streak_history = StreakCalculator.calculate_streak_period(all_dates, start_date, end_date)

            formatted_streak_history = [
                {"date": date_str, "streak": active} for date_str, active in streak_history.items()
            ]

            ent_subject_spend_time = self._calculate_ent_spend_time(
                student_id, start_datetime, end_datetime, ExamType.by_subject
            )
            ent_full_spend_time = self._calculate_ent_spend_time(
                student_id, start_datetime, end_datetime, ExamType.full_exam
            )
            trainer_spend_time = self._calculate_trainer_spend_time(student_id, start_datetime, end_datetime)
            daily_spend_time = self._calculate_daily_spend_time(student_id, start_datetime, end_datetime)

            ent_subject_dto = EntStatisticSummaryDTO(
                period_attempts_count=period_ent_subject["period_attempts_count"],
                period_total_questions=period_ent_subject["total_questions"],
                period_correct_answers=period_ent_subject["correct_answers"],
                period_accuracy=period_ent_subject["accuracy"],
                overall_total_questions=overall_ent_subject["total_questions"],
                overall_correct_answers=overall_ent_subject["correct_answers"],
                overall_accuracy=overall_ent_subject["accuracy"],
                overall_average_score=overall_ent_subject["average_score"],
                period_progress_by_subject=self._convert_to_subject_progress_dto(
                    period_ent_subject["progress_by_subject"]
                ),
                overall_progress_by_subject=self._convert_to_subject_progress_dto(
                    overall_ent_subject["progress_by_subject"]
                ),
                current_streak=period_ent_subject["current_streak"],
                total_spend_time_seconds=ent_subject_spend_time,
                total_spend_time_formatted=self._format_seconds(ent_subject_spend_time),
                exam_type="by_subject",
            )

            ent_full_dto = EntStatisticSummaryDTO(
                period_attempts_count=period_ent_full["period_attempts_count"],
                period_total_questions=period_ent_full["total_questions"],
                period_correct_answers=period_ent_full["correct_answers"],
                period_accuracy=period_ent_full["accuracy"],
                overall_total_questions=overall_ent_full["total_questions"],
                overall_correct_answers=overall_ent_full["correct_answers"],
                overall_accuracy=overall_ent_full["accuracy"],
                overall_average_score=overall_ent_full["average_score"],
                period_progress_by_subject=self._convert_to_subject_progress_dto(
                    period_ent_full["progress_by_subject"]
                ),
                overall_progress_by_subject=self._convert_to_subject_progress_dto(
                    overall_ent_full["progress_by_subject"]
                ),
                current_streak=period_ent_full["current_streak"],
                total_spend_time_seconds=ent_full_spend_time,
                total_spend_time_formatted=self._format_seconds(ent_full_spend_time),
                exam_type="full_exam",
            )

            trainer_dto = TrainerStatisticSummaryDTO(
                period_attempts_count=period_trainer["period_attempts_count"],
                period_total_questions=period_trainer["total_questions"],
                period_correct_answers=period_trainer["correct_answers"],
                period_accuracy=period_trainer["accuracy"],
                overall_total_questions=overall_trainer["total_questions"],
                overall_correct_answers=overall_trainer["correct_answers"],
                overall_accuracy=overall_trainer["accuracy"],
                period_progress_by_topic=self._convert_to_topic_progress_dto(
                    period_trainer.get("progress_by_topic", [])
                ),
                period_progress_by_subject=self._convert_to_subject_progress_dto(
                    period_trainer.get("progress_by_subject", [])
                ),
                overall_progress_by_subject=self._convert_to_subject_progress_dto(
                    overall_trainer["progress_by_subject"]
                ),
                overall_progress_by_topic=self._convert_to_topic_progress_dto(overall_trainer["progress_by_topic"]),
                current_streak=period_trainer["current_streak"],
                total_spend_time_seconds=trainer_spend_time,
                total_spend_time_formatted=self._format_seconds(trainer_spend_time),
            )

            daily_dto = DailyStatisticSummaryDTO(
                period_attempts_count=period_daily["period_attempts_count"],
                period_total_questions=period_daily["total_questions"],
                period_correct_answers=period_daily["correct_answers"],
                period_accuracy=period_daily["accuracy"],
                overall_total_questions=overall_daily["total_questions"],
                overall_correct_answers=overall_daily["correct_answers"],
                overall_accuracy=overall_daily["accuracy"],
                period_progress_by_subject=self._convert_to_subject_progress_dto(period_daily["progress_by_subject"]),
                overall_progress_by_subject=self._convert_to_subject_progress_dto(overall_daily["progress_by_subject"]),
                current_streak=period_daily["current_streak"],
                total_spend_time_seconds=daily_spend_time,
                total_spend_time_formatted=self._format_seconds(daily_spend_time),
            )

            total_attempts = (
                period_ent_subject["period_attempts_count"]
                + period_ent_full["period_attempts_count"]
                + period_trainer["period_attempts_count"]
                + period_daily["period_attempts_count"]
            )

            total_questions = (
                period_ent_subject["total_questions"]
                + period_ent_full["total_questions"]
                + period_trainer["total_questions"]
                + period_daily["total_questions"]
            )

            total_correct_answers = (
                period_ent_subject["correct_answers"]
                + period_ent_full["correct_answers"]
                + period_trainer["correct_answers"]
                + period_daily["correct_answers"]
            )

            overall_accuracy = (
                MathUtils.calculate_accuracy(total_correct_answers, total_questions) if total_questions > 0 else 0.0
            )

            activity_level = StreakCalculator.get_activity_level(total_attempts, period_days)

            engagement_score = self._calculate_engagement_score(
                total_attempts=total_attempts,
                total_questions=total_questions,
                overall_accuracy=overall_accuracy,
                current_streak=current_streak,
                period_days=period_days,
            )

            recommendations = self._generate_recommendations(
                ent_subject_statistic=period_ent_subject,
                ent_full_statistic=period_ent_full,
                trainer_statistic=trainer_dto.dict(),
                daily_statistic=daily_dto.dict(),
                overall_accuracy=overall_accuracy,
                total_attempts=total_attempts,
            )

            screen_time_history = []
            screen_time_by_activity = {
                "ent_subject": {},
                "ent_full": {},
                "trainer": {},
                "daily": {},
                "other": {},
            }
            total_screen_time_seconds = 0
            average_daily_screen_time_seconds = 0
            average_daily_screen_time = "0m"

            if self.analytic_service:
                try:
                    screen_time_data = self.analytic_service.get_user_screen_time_by_activity(
                        student_id, start_date, end_date
                    )

                    if screen_time_data:
                        total_screen_time = screen_time_data.total

                        for daily in total_screen_time.daily_screen_times:
                            screen_time_history.append(
                                {
                                    "date": daily.date.isoformat(),
                                    "screen_time_seconds": daily.screen_time_seconds,
                                    "screen_time_formatted": daily.screen_time_formatted,
                                }
                            )

                        total_screen_time_seconds = total_screen_time.total_screen_time_seconds
                        average_daily_screen_time_seconds = total_screen_time.average_daily_screen_time_seconds

                        avg_seconds = average_daily_screen_time_seconds
                        avg_hours = avg_seconds // 3600
                        avg_minutes = (avg_seconds % 3600) // 60
                        if avg_hours > 0:
                            average_daily_screen_time = f"{avg_hours}h {avg_minutes}m"
                        elif avg_minutes > 0:
                            average_daily_screen_time = f"{avg_minutes}m"
                        else:
                            average_daily_screen_time = f"{avg_seconds}s"

                        screen_time_by_activity = {
                            "ent_subject": self._format_activity_screen_time(
                                getattr(screen_time_data, "ent_subject", None) or getattr(screen_time_data, "ent", None)
                            ),
                            "ent_full": self._format_activity_screen_time(getattr(screen_time_data, "ent_full", None)),
                            "trainer": self._format_activity_screen_time(screen_time_data.trainer),
                            "daily": self._format_activity_screen_time(screen_time_data.daily),
                            "other": self._format_activity_screen_time(screen_time_data.other),
                        }
                except Exception as e:
                    logger.warning("Failed to get screen time: %s", e, exc_info=True)

            result = {
                "period": request.period_type.value,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "ent_statistics": {
                    "by_subject": ent_subject_dto.dict(),
                    "full_exam": ent_full_dto.dict(),
                },
                "trainer": trainer_dto.dict(),
                "daily": daily_dto.dict(),
                "total_attempts": total_attempts,
                "total_questions": total_questions,
                "total_correct_answers": total_correct_answers,
                "overall_accuracy": round(overall_accuracy, 6),
                "period_info": {
                    "period_type": request.period_type.value,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "description": description,
                },
                "streak_history": formatted_streak_history,
                "current_streak": current_streak,
                "ent_subject_max_streak": ent_subject_max_streak,
                "ent_full_max_streak": ent_full_max_streak,
                "trainer_max_streak": trainer_max_streak,
                "daily_max_streak": daily_max_streak,
                "max_streak_in_period": max_streak_in_period,
                "screen_time_history": screen_time_history,
                "screen_time_by_activity": screen_time_by_activity,
                "total_screen_time_seconds": total_screen_time_seconds,
                "average_daily_screen_time_seconds": average_daily_screen_time_seconds,
                "average_daily_screen_time": average_daily_screen_time,
                "screen_time_trend_percentage": self._compute_screen_time_trend(
                    screen_time_history
                ),
                "full_ent_attempts_history": self._compute_full_ent_attempts_history(
                    student_id
                ),
                "activity_level": activity_level,
                "engagement_score": engagement_score,
                "recommendations": recommendations,
            }

        validation_errors = StatisticValidator.validate_statistics_consistency(result)
        if validation_errors:
            logger.warning("Statistic validation warnings: %s", validation_errors)

        return result

    @staticmethod
    def _compute_screen_time_trend(history: list[dict]) -> int | None:
        """Trend of screen-time engagement across the returned window.

        Splits the history into two halves and compares the second half's
        average to the first half's. Positive → engagement growing,
        negative → falling off. Capped to ±99 so the frontend «↓ 23%»
        badge never overflows the card.

        Returns None when the data isn't actionable:
        - fewer than 4 days in the window (can't make 2-vs-2 comparison)
        - either half is empty
        - first half average is zero (would div-by-zero / report ∞%)
        """
        if not history or len(history) < 4:
            return None

        mid = len(history) // 2
        prior = history[:mid]
        recent = history[mid:]
        if not prior or not recent:
            return None

        def avg(items: list[dict]) -> float:
            total = sum(int(it.get("screen_time_seconds", 0) or 0) for it in items)
            return total / len(items)

        prior_avg = avg(prior)
        recent_avg = avg(recent)
        if prior_avg <= 0:
            return None

        delta_pct = round((recent_avg - prior_avg) / prior_avg * 100)
        if delta_pct == 0:
            return None
        return max(-99, min(99, delta_pct))

    def _compute_full_ent_attempts_history(
        self, student_id: UUID
    ) -> list[dict[str, Any]]:
        """Завершённые попытки Полного ЕНТ за последние 365 дней.

        Каждая строка — `{completed_at: ISO8601, score_percentage: int}`,
        сортировка по `completed_at` DESC (newest first). Это сырьё для
        pill-чарта на экране статистики; клиент группирует список в 7/4/12
        бакетов в зависимости от выбранного периода (неделя/месяц/год).

        Считаем только `exam_type=full_exam, status=completed` — операторское
        решение от 27.05.2026: «по-предметные» тесты сюда не идут.

        Процент = `score / total_questions * 100`. `total_questions` берём
        из `full_exam_question_ids` (CSV). Попытки с пустым CSV — невалидные,
        пропускаем (есть warning в логах при `get_attempt_statistic`).
        """
        from quiz.dtos.enums import Status
        from quiz.models.ent import EntAttempt

        cutoff = datetime.utcnow() - timedelta(days=365)
        attempts = (
            self.uow.ent_attempts._session.query(EntAttempt)
            .filter(
                EntAttempt.student_guid == student_id,
                EntAttempt.exam_type == ExamType.full_exam,
                EntAttempt.status == Status.completed,
                EntAttempt.completed_at.isnot(None),
                EntAttempt.completed_at >= cutoff,
            )
            .order_by(EntAttempt.completed_at.desc())
            .all()
        )

        result: list[dict[str, Any]] = []
        for a in attempts:
            item = self._project_full_ent_attempt(
                score=a.score,
                full_exam_question_ids=a.full_exam_question_ids,
                completed_at=a.completed_at,
            )
            if item is not None:
                result.append(item)
        return result

    @staticmethod
    def _project_full_ent_attempt(
        *,
        score: int | None,
        full_exam_question_ids: str | None,
        completed_at: datetime | None,
    ) -> dict[str, Any] | None:
        """Pure projection of one EntAttempt → history row.

        Returns None when the row isn't representable: missing
        `completed_at`, empty `full_exam_question_ids`, or unparseable
        question count. Percentage is clamped to [0, 100] — protects the
        client chart against bad data (negative score, score > total_questions
        from a partial backfill) without hiding the underlying attempt
        from the count.
        """
        if completed_at is None:
            return None
        csv = (full_exam_question_ids or "").strip()
        if not csv:
            return None
        total_questions = len([q for q in csv.split(",") if q.strip()])
        if total_questions <= 0:
            return None
        pct = round((score or 0) / total_questions * 100)
        pct = max(0, min(100, pct))
        # Append explicit UTC marker. `completed_at` is naive-UTC in the DB
        # (Column(DateTime), no tz) but Dart `DateTime.parse` of a string
        # without timezone treats it as LOCAL — shifting absolute time by
        # the user's offset (KZ is UTC+5 → would land 5 hours early).
        # Forcing `Z` keeps the client-side bucketing aligned with what
        # the server thinks the attempt's calendar date is.
        iso = completed_at.isoformat()
        if not iso.endswith("Z") and "+" not in iso[10:]:
            iso = iso + "Z"
        return {
            "completed_at": iso,
            "score_percentage": pct,
        }

    def _convert_to_subject_progress_dto(self, subject_list: list[dict]) -> list[SubjectProgressDTO]:
        """Конвертировать список словарей в список SubjectProgressDTO"""
        return [
            SubjectProgressDTO(
                subject_id=subject["subject_id"],
                subject_name=subject["subject_name"],
                total_questions=subject["total_questions"],
                correct_answers=subject["correct_answers"],
                accuracy=subject.get("accuracy", 0.0),
            )
            for subject in subject_list
        ]

    def _convert_to_topic_progress_dto(self, topic_list: list[dict]) -> list[TopicProgressDTO]:
        """Конвертировать список словарей в список TopicProgressDTO"""
        return [
            TopicProgressDTO(
                topic_id=topic["topic_id"],
                topic_name=topic["topic_name"],
                subject_id=topic["subject_id"],
                subject_name=topic["subject_name"],
                total_questions=topic["total_questions"],
                correct_answers=topic["correct_answers"],
                accuracy=topic.get("accuracy", 0.0),
            )
            for topic in topic_list
        ]

    def _get_period_ent_statistic(
        self,
        student_id: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType,
    ) -> dict[str, Any]:
        """Получить статистику ЕНТ ЗА ПЕРИОД"""
        attempts = self.uow.ent_attempts.get_completed_attempts_by_period(student_id, start_date, end_date, exam_type)

        if not attempts:
            return self._get_empty_ent_statistic()

        total_questions = 0
        total_correct = 0
        total_score = 0
        progress_by_subject = {}

        for attempt in attempts:
            attempt_stats = self.uow.ent_attempts.get_attempt_statistic(attempt.id, None)

            total_questions += attempt_stats.total_questions
            total_correct += attempt_stats.correct
            total_score += attempt_stats.score

            answers_with_questions = self.uow.ent_attempts.get_attempt_answers_with_questions(attempt.id)

            for answer in answers_with_questions:
                if answer.variant and answer.variant.question:
                    question = answer.variant.question
                    subject_id = getattr(question, "subject_id", None)

                    if subject_id:
                        if subject_id not in progress_by_subject:
                            subject_name = (
                                getattr(question.subject, "name", f"Subject {subject_id}")
                                if hasattr(question, "subject") and question.subject
                                else f"Subject {subject_id}"
                            )

                            progress_by_subject[subject_id] = {
                                "subject_id": subject_id,
                                "subject_name": subject_name,
                                "total_questions": 0,
                                "correct_answers": 0,
                            }

                        progress_by_subject[subject_id]["total_questions"] += 1

                        if answer.variant.is_correct:
                            progress_by_subject[subject_id]["correct_answers"] += 1

        for subject_data in progress_by_subject.values():
            if subject_data["total_questions"] > 0:
                subject_data["accuracy"] = MathUtils.calculate_accuracy(
                    subject_data["correct_answers"], subject_data["total_questions"]
                )
            else:
                subject_data["accuracy"] = 0.0

        period_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)
        period_progress_by_subject = list(progress_by_subject.values())

        ent_dates = {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}
        current_streak = StreakCalculator.calculate_streak_on_date(ent_dates, to_kz_date(end_date), include_target_date=True)

        return {
            "period_attempts_count": len(attempts),
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": period_accuracy,
            "average_score": total_score / len(attempts) if attempts else 0,
            "progress_by_subject": period_progress_by_subject,
            "current_streak": current_streak,
        }

    def _get_overall_ent_statistic(
        self,
        student_id: UUID,
        exam_type: ExamType,
    ) -> dict[str, Any]:
        """Получить ОБЩУЮ статистику ЕНТ за всё время"""
        attempts = self.uow.ent_attempts.get_all_completed_attempts(student_id, exam_type)

        if not attempts:
            return {
                "total_questions": 0,
                "correct_answers": 0,
                "accuracy": 0.0,
                "average_score": 0.0,
                "progress_by_subject": [],
            }

        total_questions = 0
        total_correct = 0
        total_score = 0

        subject_stats = self.uow.ent_attempts.get_attempt_subjects_statistics(student_id, exam_type)

        for attempt in attempts:
            attempt_stats = self.uow.ent_attempts.get_attempt_statistic(attempt.id, None)
            total_questions += attempt_stats.total_questions
            total_correct += attempt_stats.correct
            total_score += attempt_stats.score

        overall_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)
        average_score = total_score / len(attempts) if attempts else 0

        overall_progress_by_subject = []
        for subject_id, stats in subject_stats.items():
            if stats["total_questions"] > 0:
                accuracy = MathUtils.calculate_accuracy(stats["correct_answers"], stats["total_questions"])
            else:
                accuracy = 0.0

            overall_progress_by_subject.append(
                {
                    "subject_id": subject_id,
                    "subject_name": stats["subject_name"],
                    "total_questions": stats["total_questions"],
                    "correct_answers": stats["correct_answers"],
                    "accuracy": accuracy,
                }
            )

        return {
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": overall_accuracy,
            "average_score": average_score,
            "progress_by_subject": overall_progress_by_subject,
        }

    def _get_period_trainer_statistic(
        self,
        student_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """Получить статистику тренажеров ЗА ПЕРИОД"""
        attempts = self.uow.trainer_attempts.get_all_completed_attempts_by_period(student_id, start_date, end_date)

        if not attempts:
            return self._get_empty_trainer_statistic()

        total_questions = 0
        total_correct = 0
        progress_by_topic = {}
        progress_by_subject = {}

        for attempt in attempts:
            attempt_stats = self.uow.trainer_attempts.get_attempt_statistic(attempt.id)

            total_questions += attempt_stats.get("total_questions", 0)
            total_correct += attempt_stats.get("correct", 0)

            if hasattr(attempt, "questions") and attempt.questions:
                for question_attempt in attempt.questions:
                    if hasattr(question_attempt, "question") and question_attempt.question:
                        question = question_attempt.question
                        topic_id = getattr(question, "topic_id", None)
                        topic_name = (
                            getattr(question.topic, "name", f"Topic {topic_id}")
                            if hasattr(question, "topic") and question.topic
                            else f"Topic {topic_id}"
                        )
                        subject_id = getattr(question, "subject_id", None)
                        subject_name = (
                            getattr(question.subject, "name", f"Subject {subject_id}")
                            if hasattr(question, "subject") and question.subject
                            else f"Subject {subject_id}"
                        )

                        is_correct = False
                        if question_attempt.answers:
                            correct_variant_ids = {v.id for v in question.variants if v.is_correct}
                            chosen_variant_ids = {a.variant_id for a in question_attempt.answers if a.variant_id}
                            is_correct = chosen_variant_ids == correct_variant_ids

                        if topic_id and subject_id:
                            if topic_id not in progress_by_topic:
                                progress_by_topic[topic_id] = {
                                    "topic_id": topic_id,
                                    "topic_name": topic_name,
                                    "subject_id": subject_id,
                                    "subject_name": subject_name,
                                    "total_questions": 0,
                                    "correct_answers": 0,
                                }

                            progress_by_topic[topic_id]["total_questions"] += 1
                            if is_correct:
                                progress_by_topic[topic_id]["correct_answers"] += 1

                        if subject_id:
                            if subject_id not in progress_by_subject:
                                progress_by_subject[subject_id] = {
                                    "subject_id": subject_id,
                                    "subject_name": subject_name,
                                    "total_questions": 0,
                                    "correct_answers": 0,
                                }

                            progress_by_subject[subject_id]["total_questions"] += 1
                            if is_correct:
                                progress_by_subject[subject_id]["correct_answers"] += 1

        for topic_data in progress_by_topic.values():
            topic_data["accuracy"] = MathUtils.calculate_accuracy(
                topic_data["correct_answers"], topic_data["total_questions"]
            )

        for subject_data in progress_by_subject.values():
            subject_data["accuracy"] = MathUtils.calculate_accuracy(
                subject_data["correct_answers"], subject_data["total_questions"]
            )

        period_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)

        trainer_dates = {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}
        current_streak = StreakCalculator.calculate_streak_on_date(
            trainer_dates, to_kz_date(end_date), include_target_date=True
        )

        progress_by_topic_list = list(progress_by_topic.values())
        progress_by_subject_list = list(progress_by_subject.values())

        return {
            "period_attempts_count": len(attempts),
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": period_accuracy,
            "progress_by_topic": progress_by_topic_list,
            "progress_by_subject": progress_by_subject_list,
            "current_streak": current_streak,
        }

    def _get_overall_trainer_statistic(
        self,
        student_id: UUID,
    ) -> dict[str, Any]:
        """Получить ОБЩУЮ статистику тренажеров за всё время"""
        attempts = self.uow.trainer_attempts.get_all_completed_attempts(student_id)

        if not attempts:
            return {
                "total_questions": 0,
                "correct_answers": 0,
                "accuracy": 0.0,
                "progress_by_subject": [],
                "progress_by_topic": [],
            }

        total_questions = 0
        total_correct = 0

        for attempt in attempts:
            attempt_stats = self.uow.trainer_attempts.get_attempt_statistic(attempt.id)
            total_questions += attempt_stats.get("total_questions", 0)
            total_correct += attempt_stats.get("correct", 0)

        overall_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)

        subject_stats = self.uow.trainer_attempts.get_overall_subject_progress(student_id)
        topic_stats = self.uow.trainer_attempts.get_overall_topic_progress(student_id)

        overall_progress_by_subject = []
        for subject_id, stats in subject_stats.items():
            if stats["total_questions"] > 0:
                accuracy = MathUtils.calculate_accuracy(stats["correct_answers"], stats["total_questions"])
            else:
                accuracy = 0.0

            overall_progress_by_subject.append(
                {
                    "subject_id": subject_id,
                    "subject_name": stats["subject_name"],
                    "total_questions": stats["total_questions"],
                    "correct_answers": stats["correct_answers"],
                    "accuracy": accuracy,
                }
            )

        overall_progress_by_topic = []
        for topic_id, stats in topic_stats.items():
            if stats["total_questions"] > 0:
                accuracy = MathUtils.calculate_accuracy(stats["correct_answers"], stats["total_questions"])
            else:
                accuracy = 0.0

            overall_progress_by_topic.append(
                {
                    "topic_id": topic_id,
                    "topic_name": stats["topic_name"],
                    "subject_id": stats["subject_id"],
                    "subject_name": stats["subject_name"],
                    "total_questions": stats["total_questions"],
                    "correct_answers": stats["correct_answers"],
                    "accuracy": accuracy,
                }
            )

        return {
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": overall_accuracy,
            "progress_by_subject": overall_progress_by_subject,
            "progress_by_topic": overall_progress_by_topic,
        }

    def _get_period_daily_statistic(
        self,
        student_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """Получить статистику daily тестов ЗА ПЕРИОД"""
        attempts = self.uow.daily_tests.get_completed_attempts_by_period(student_id, start_date, end_date)

        if not attempts:
            return self._get_empty_daily_statistic()

        total_questions = 0
        total_correct = 0
        progress_by_subject = {}

        for attempt in attempts:
            attempt_total = attempt.correct_answers + attempt.incorrect_answers + attempt.skipped_answers
            total_questions += attempt_total
            total_correct += attempt.correct_answers

            if attempt.subject_id:
                subject_id = attempt.subject_id
                subject_name = getattr(attempt.subject, "name", f"Subject {subject_id}")

                if subject_id not in progress_by_subject:
                    progress_by_subject[subject_id] = {
                        "subject_id": subject_id,
                        "subject_name": subject_name,
                        "total_questions": 0,
                        "correct_answers": 0,
                    }

                progress_by_subject[subject_id]["total_questions"] += attempt_total
                progress_by_subject[subject_id]["correct_answers"] += attempt.correct_answers
            else:
                try:
                    questions = self.uow.daily_tests.get_attempt_questions(attempt.id)
                    answers = self.uow.daily_tests.get_attempt_answers(attempt.id)

                    answers_dict = {}
                    for answer in answers:
                        if answer.question_id not in answers_dict:
                            answers_dict[answer.question_id] = []
                        if answer.variant_id:
                            answers_dict[answer.question_id].append(answer.variant_id)

                    for question in questions:
                        subject_id = question.subject_id
                        subject_name = question.subject.name if question.subject else f"Subject {subject_id}"

                        if subject_id not in progress_by_subject:
                            progress_by_subject[subject_id] = {
                                "subject_id": subject_id,
                                "subject_name": subject_name,
                                "total_questions": 0,
                                "correct_answers": 0,
                            }

                        progress_by_subject[subject_id]["total_questions"] += 1

                        user_variant_ids = answers_dict.get(question.id, [])
                        if user_variant_ids:
                            correct_variant_ids = {v.id for v in question.variants if v.is_correct}

                            if len(user_variant_ids) == 1 and len(correct_variant_ids) == 1:
                                is_correct = user_variant_ids[0] in correct_variant_ids
                            else:
                                is_correct = set(user_variant_ids) == correct_variant_ids

                            if is_correct:
                                progress_by_subject[subject_id]["correct_answers"] += 1
                except Exception as e:
                    logger.warning("Error processing daily attempt %s: %s", attempt.id, e)
                    continue

        for subject_data in progress_by_subject.values():
            if subject_data["total_questions"] > 0:
                subject_data["accuracy"] = MathUtils.calculate_accuracy(
                    subject_data["correct_answers"], subject_data["total_questions"]
                )
            else:
                subject_data["accuracy"] = 0.0

        period_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)

        daily_dates = {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}
        current_streak = StreakCalculator.calculate_streak_on_date(
            daily_dates, to_kz_date(end_date), include_target_date=True
        )

        progress_by_subject_list = list(progress_by_subject.values())

        return {
            "period_attempts_count": len(attempts),
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": period_accuracy,
            "progress_by_subject": progress_by_subject_list,
            "current_streak": current_streak,
        }

    def _get_overall_daily_statistic(
        self,
        student_id: UUID,
    ) -> dict[str, Any]:
        """Получить ОБЩУЮ статистику daily тестов за всё время"""
        attempts = self.uow.daily_tests.get_all_completed_attempts(student_id)

        if not attempts:
            return {
                "total_questions": 0,
                "correct_answers": 0,
                "accuracy": 0.0,
                "progress_by_subject": [],
            }

        total_questions = 0
        total_correct = 0

        subject_stats = self.uow.daily_tests.get_overall_subject_progress(student_id)

        for attempt in attempts:
            attempt_total = attempt.correct_answers + attempt.incorrect_answers + attempt.skipped_answers
            total_questions += attempt_total
            total_correct += attempt.correct_answers

        overall_accuracy = MathUtils.calculate_accuracy(total_correct, total_questions)

        overall_progress_by_subject = []
        for subject_id, stats in subject_stats.items():
            if stats["total_questions"] > 0:
                accuracy = MathUtils.calculate_accuracy(stats["correct_answers"], stats["total_questions"])
            else:
                accuracy = 0.0

            overall_progress_by_subject.append(
                {
                    "subject_id": subject_id,
                    "subject_name": stats["subject_name"],
                    "total_questions": stats["total_questions"],
                    "correct_answers": stats["correct_answers"],
                    "accuracy": accuracy,
                }
            )

        return {
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy": overall_accuracy,
            "progress_by_subject": overall_progress_by_subject,
        }

    def _get_empty_ent_statistic(self) -> dict[str, Any]:
        return {
            "period_attempts_count": 0,
            "total_questions": 0,
            "correct_answers": 0,
            "accuracy": 0.0,
            "average_score": 0.0,
            "progress_by_subject": [],
            "current_streak": 0,
        }

    def _get_empty_trainer_statistic(self) -> dict[str, Any]:
        return {
            "period_attempts_count": 0,
            "total_questions": 0,
            "correct_answers": 0,
            "accuracy": 0.0,
            "progress_by_topic": [],
            "progress_by_subject": [],
            "current_streak": 0,
        }

    def _get_empty_daily_statistic(self) -> dict[str, Any]:
        return {
            "period_attempts_count": 0,
            "total_questions": 0,
            "correct_answers": 0,
            "accuracy": 0.0,
            "progress_by_subject": [],
            "current_streak": 0,
        }

    def _calculate_ent_spend_time(
        self,
        student_id: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType,
    ) -> int:
        attempts = self.uow.ent_attempts.get_completed_attempts_by_period(student_id, start_date, end_date, exam_type)

        total_spend_time = 0
        for attempt in attempts:
            attempt_stats = self.uow.ent_attempts.get_attempt_statistic(attempt.id, None)
            total_spend_time += getattr(attempt_stats, "spend_time", 0)

        return total_spend_time

    def _calculate_trainer_spend_time(self, student_id: UUID, start_date: datetime, end_date: datetime) -> int:
        attempts = self.uow.trainer_attempts.get_all_completed_attempts_by_period(student_id, start_date, end_date)

        total_spend_time = 0
        for attempt in attempts:
            attempt_stats = self.uow.trainer_attempts.get_attempt_statistic(attempt.id)
            total_spend_time += attempt_stats.get("spend_time", 0)

        return total_spend_time

    def _calculate_daily_spend_time(self, student_id: UUID, start_date: datetime, end_date: datetime) -> int:
        attempts = self.uow.daily_tests.get_completed_attempts_by_period(student_id, start_date, end_date)

        total_spend_time = 0
        for attempt in attempts:
            total_spend_time += getattr(attempt, "spend_time", 0)

        return total_spend_time

    def _format_seconds(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            if secs == 0:
                return f"{minutes}m"
            else:
                return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def _format_activity_screen_time(self, screen_time_dto: Any) -> dict[str, Any]:
        if not screen_time_dto:
            return {}

        return {
            "total_seconds": getattr(screen_time_dto, "total_screen_time_seconds", 0),
            "average_daily_seconds": getattr(screen_time_dto, "average_daily_screen_time_seconds", 0),
            "history": [
                {
                    "date": getattr(daily, "date", "").isoformat(),
                    "screen_time_seconds": getattr(daily, "screen_time_seconds", 0),
                    "screen_time_formatted": getattr(daily, "screen_time_formatted", "0s"),
                }
                for daily in getattr(screen_time_dto, "daily_screen_times", [])
            ],
        }

    def _get_completed_dates_for_ent(
        self,
        student_id: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType,
    ) -> set[date]:
        """Получить даты завершенных попыток ЕНТ за период.

        Returns KZ-local dates: an attempt completed at 22:00 UTC counts as
        the next day in Almaty (03:00 the following morning local time),
        which is what the user perceives and what the streak should reflect.
        """
        attempts = self.uow.ent_attempts.get_completed_attempts_by_period(student_id, start_date, end_date, exam_type)
        return {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}

    def _get_completed_dates_for_trainer(self, student_id: UUID, start_date: datetime, end_date: datetime) -> set[date]:
        """Получить даты завершенных попыток тренажеров за период (KZ-local)."""
        attempts = self.uow.trainer_attempts.get_all_completed_attempts_by_period(student_id, start_date, end_date)
        return {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}

    def _get_completed_dates_for_daily(self, student_id: UUID, start_date: datetime, end_date: datetime) -> set[date]:
        """Получить даты завершенных попыток daily тестов за период (KZ-local)."""
        attempts = self.uow.daily_tests.get_completed_attempts_by_period(student_id, start_date, end_date)
        return {kz_date for attempt in attempts if (kz_date := to_kz_date(attempt.completed_at)) is not None}

    def _calculate_engagement_score(
        self,
        total_attempts: int,
        total_questions: int,
        overall_accuracy: float,
        current_streak: int,
        period_days: int = 7,
    ) -> float:
        if period_days == 0:
            return 0.0

        attempts_score = min(total_attempts / (period_days * 2), 1.0)
        questions_score = min(total_questions / (period_days * 10), 1.0)
        accuracy_score = overall_accuracy
        streak_score = min(current_streak / 7, 1.0)

        total_score = attempts_score * 25 + questions_score * 25 + accuracy_score * 30 + streak_score * 20

        return round(min(total_score, 100.0), 2)

    def _generate_recommendations(
        self,
        ent_subject_statistic: dict[str, Any],
        ent_full_statistic: dict[str, Any],
        trainer_statistic: dict[str, Any],
        daily_statistic: dict[str, Any],
        overall_accuracy: float,
        total_attempts: int,
    ) -> list[str]:
        recommendations = []

        if overall_accuracy < 0.5:
            recommendations.append("Поработайте над точностью ответов. Попробуйте повторить сложные темы.")
        elif overall_accuracy < 0.7:
            recommendations.append("Хороший результат! Есть куда расти - поработайте над сложными темами.")
        else:
            recommendations.append("Отличная точность! Продолжайте в том же духе.")

        if total_attempts == 0:
            recommendations.append("Начните регулярные занятия для достижения лучших результатов.")
        elif total_attempts < 3:
            recommendations.append("Увеличьте количество попыток для более эффективной подготовки.")
        else:
            recommendations.append("Вы делаете отличные успехи! Продолжайте регулярно заниматься.")

        if ent_subject_statistic.get("period_attempts_count", 0) == 0:
            recommendations.append("Попробуйте пройти тесты ЕНТ по предметам для лучшей подготовки.")

        if ent_full_statistic.get("period_attempts_count", 0) == 0:
            recommendations.append("Рекомендуем пройти полный экзамен ЕНТ для симуляции реальных условий.")

        if trainer_statistic.get("period_attempts_count", 0) > 0 and trainer_statistic.get("period_accuracy", 0) < 0.6:
            recommendations.append("Обратите внимание на тренажеры, там вы можете улучшить знания по конкретным темам.")

        if daily_statistic.get("period_attempts_count", 0) == 0:
            recommendations.append("Ежедневные тесты помогут поддерживать знания в тонусе.")

        return recommendations[:3]
