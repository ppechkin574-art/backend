import logging
from datetime import UTC, datetime, timedelta

# from uuid import UUID
from quiz.dtos.enums import Status
from quiz.dtos.progress import (
    # EntOptionProgressDetailDTO,
    EntOptionsProgressSummaryDTO,
    SubjectProgressDTO,
    TopicProgressDTO,
    # TrainerProgressDetailDTO,
    TrainersProgressSummaryDTO,
    UserProgressOverviewDTO,
)
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached


class ProgressService:
    """Сервис для работы с прогрессом пользователя"""

    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service
        self.logger = logging.getLogger(__name__)

    def record_progress(
        self,
        user_id: str,
        question_id: int,
        is_correct: bool,
        attempt_type: str,
        attempt_id: int,
    ) -> None:
        """Записать прогресс пользователя"""
        with self._uow:
            self._uow.progress.record_progress(
                user_id=user_id,
                question_id=question_id,
                is_correct=is_correct,
                attempt_type=attempt_type,
                attempt_id=attempt_id,
            )
            self._uow.commit()
            self._invalidate_progress_cache(user_id)
            self.logger.info("Invalidated progress cache for user %s", user_id)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="topic_progress")
    def get_topic_progress(self, user_id: str, topic_id: int, only_correct: bool = True) -> float:
        """Получить прогресс по теме как число от 0 до 1"""
        with self._uow:
            progress = self._uow.progress.get_topic_progress(
                user_id=user_id,
                topic_id=topic_id,
                only_correct=only_correct,
            )
            return round(progress, 2)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="subject_progress")
    def get_subject_progress(self, user_id: str, subject_id: int, only_correct: bool = True) -> float:
        """Получить прогресс по предмету как число от 0 до 1"""
        with self._uow:
            progress = self._uow.progress.get_subject_progress(
                user_id=user_id,
                subject_id=subject_id,
                only_correct=only_correct,
            )
            return round(progress, 2)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="trainers_progress_summary")
    def get_trainers_progress_summary(self, user_id: str) -> TrainersProgressSummaryDTO:
        """Получить сводку прогресса по всем тренажёрам"""
        try:
            with self._uow:
                # Получаем все тренажёры
                trainers = self._uow.trainers.get_all_trainers()

                if not trainers:
                    return TrainersProgressSummaryDTO.from_values(0, 0, 0.0)

                total_trainers = len(trainers)
                trainers_with_progress = []
                completed_trainers = 0

                for trainer in trainers:
                    # ПРОВЕРЯЕМ: есть ли вообще попытки у этого тренажёра
                    has_attempts = self._has_trainer_attempts(user_id, trainer.id)

                    if has_attempts:
                        # Только если есть попытки, считаем прогресс
                        progress = self.get_trainer_progress(user_id, trainer.id)
                        trainers_with_progress.append(
                            {
                                "trainer_id": trainer.id,
                                "trainer_name": trainer.name,
                                "progress": progress,
                                "has_attempts": True,
                            }
                        )
                        completed_trainers += 1

                # Логируем детальную информацию
                self.logger.info("Trainers progress for user %s:", user_id)
                self.logger.info("  Total trainers: %s", total_trainers)
                self.logger.info("  Trainers with attempts: %s", completed_trainers)

                if trainers_with_progress:
                    total_progress = sum(item["progress"] for item in trainers_with_progress)
                    # Средний прогресс только по тренажёрам с попытками
                    avg_progress_for_completed = total_progress / completed_trainers if completed_trainers > 0 else 0.0

                    # Общий прогресс по всем тренажёрам (учитывая нули для без попыток)
                    overall_progress = total_progress / total_trainers if total_trainers > 0 else 0.0

                    self.logger.info("  Total progress sum: %s", round(total_progress, 2))
                    self.logger.info(
                        "  Average progress (completed only): %s",
                        round(avg_progress_for_completed, 2),
                    )
                    self.logger.info(
                        "  Overall progress (all trainers): %s",
                        round(overall_progress, 2),
                    )

                    # Логируем детали по каждому тренажёру с попытками
                    for item in trainers_with_progress:
                        self.logger.info(
                            "Trainer %s (%s): progress=%s",
                            item["trainer_id"],
                            item["trainer_name"],
                            round(item["progress"], 2),
                        )

                    return TrainersProgressSummaryDTO.from_values(
                        total_trainers,
                        completed_trainers,
                        overall_progress,  # Используем overall_progress
                    )
                else:
                    self.logger.info("  No trainers with attempts found")
                    return TrainersProgressSummaryDTO.from_values(total_trainers, 0, 0.0)
        except Exception as e:
            self.logger.exception("Error calculating trainers progress: %s", str(e))
            return TrainersProgressSummaryDTO.from_values(0, 0, 0.0)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="ent_options_progress_summary")
    def get_ent_options_progress_summary(self, user_id: str) -> EntOptionsProgressSummaryDTO:
        """Получить сводку прогресса по всем вариантам ЕНТ"""
        try:
            with self._uow:
                # Получаем все варианты ЕНТ
                ent_options_result = self._uow.ent_options.get_all_ent_options(page=1, page_size=1000)

                # Обрабатываем результат
                if isinstance(ent_options_result, tuple):
                    ent_options, _ = ent_options_result
                else:
                    ent_options = ent_options_result

                if not ent_options:
                    self.logger.warning("No ENT options found for user %s", user_id)
                    return EntOptionsProgressSummaryDTO.from_values(0, 0, 0.0)

                total_options = len(ent_options)
                options_with_progress = []
                completed_options = 0

                for option in ent_options:
                    # Проверяем, есть ли попытки
                    has_attempts = self._has_ent_option_attempts(user_id, option.id)

                    if has_attempts:
                        # Только если есть попытки, считаем прогресс
                        progress = self.get_ent_option_progress(user_id, option.id)
                        options_with_progress.append(
                            {
                                "option_id": option.id,
                                "option_number": getattr(option, "option_number", option.id),
                                "progress": progress,
                                "has_attempts": True,
                            }
                        )
                        completed_options += 1

                # Логируем детальную информацию
                self.logger.info("ENT options progress for user %s:", user_id)
                self.logger.info("  Total options: %s", total_options)
                self.logger.info("  Options with attempts: %s", completed_options)

                if options_with_progress:
                    total_progress = sum(item["progress"] for item in options_with_progress)

                    # Общий прогресс по всем вариантам (учитывая нули)
                    overall_progress = total_progress / total_options if total_options > 0 else 0.0

                    self.logger.info("Total progress sum: %s", round(total_progress, 2))
                    self.logger.info("Overall progress (all options): %s", round(overall_progress, 2))

                    # Логируем детали
                    for item in options_with_progress:
                        self.logger.info(
                            "Option %s (#%s): progress=%s",
                            item["option_id"],
                            item["option_number"],
                            round(item["progress"], 2),
                        )

                    return EntOptionsProgressSummaryDTO.from_values(total_options, completed_options, overall_progress)
                else:
                    self.logger.info("  No ENT options with attempts found")
                    return EntOptionsProgressSummaryDTO.from_values(total_options, 0, 0.0)
        except Exception as e:
            self.logger.exception("Error calculating ENT progress: %s", str(e))
            return EntOptionsProgressSummaryDTO.from_values(0, 0, 0.0)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="trainer_progress")
    def get_trainer_progress(self, user_id: str, trainer_id: int) -> float:
        """Получить прогресс по конкретному тренажёру (от 0 до 1)"""
        try:
            with self._uow:
                best_attempt = self._uow.trainer_attempts.get_best_attempt_for_trainer(
                    user_id=user_id, trainer_id=trainer_id
                )

                if not best_attempt or best_attempt.status != Status.completed:
                    return 0.0

                attempt_id = getattr(best_attempt, "id", None)
                if not attempt_id:
                    self.logger.warning("Best attempt has no ID for trainer %s", trainer_id)
                    return 0.0

                attempt_with_questions = self._uow.trainer_attempts.get_with_questions(attempt_id)

                if attempt_with_questions is None:
                    self.logger.warning("get_with_questions returned None for attempt %s", attempt_id)
                    return 0.0

                if not hasattr(attempt_with_questions, "questions") or attempt_with_questions.questions is None:
                    self.logger.warning("No questions attribute in attempt %s", attempt_id)
                    return 0.0

                questions = attempt_with_questions.questions
                if not questions:
                    return 0.0

                total_questions = len(questions)
                correctly_answered = 0

                for question in questions:
                    correct_variant_ids = set()
                    if hasattr(question, "variants") and question.variants:
                        correct_variant_ids = {v.id for v in question.variants if getattr(v, "is_correct", False)}

                    chosen_variant_ids = set()
                    if hasattr(question, "answers") and question.answers:
                        chosen_variant_ids = {a.variant_id for a in question.answers if getattr(a, "variant_id", None)}

                    if correct_variant_ids and chosen_variant_ids == correct_variant_ids:
                        correctly_answered += 1

                if total_questions <= 0:
                    return 0.0

                progress = correctly_answered / total_questions
                return round(progress, 2)
        except Exception as e:
            self.logger.exception("Error getting trainer progress for trainer %s: %s", trainer_id, str(e))
            return 0.0

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="ent_option_progress")
    def get_ent_option_progress(self, user_id: str, ent_option_id: int) -> float:
        """Получить прогресс по конкретному варианту ЕНТ (от 0 до 1)"""
        try:
            with self._uow:
                # Получаем лучшую попытку
                best_attempt = self._uow.ent_attempts.get_best_attempt_for_option(
                    user_id=user_id, ent_option_id=ent_option_id
                )

                if not best_attempt:
                    self.logger.debug("No attempt found for ENT option %s", ent_option_id)
                    return 0.0

                if best_attempt.status != Status.completed:
                    self.logger.debug(
                        "Best attempt for ENT option %s not completed: status=%s",
                        ent_option_id,
                        best_attempt.status,
                    )
                    return 0.0

                # Получаем статистику попытки
                statistics = self._uow.ent_attempts.get_attempt_statistic(
                    best_attempt.id, getattr(best_attempt, "spend_time", 0)
                )

                if not statistics:
                    self.logger.debug("No statistics for ENT attempt %s", best_attempt.id)
                    return 0.0

                # Извлекаем данные
                correct = getattr(statistics, "correct", 0)
                incorrect = getattr(statistics, "incorrect", 0)
                partial_correct = getattr(statistics, "partial_correct", 0)
                skiped = getattr(statistics, "skiped", 0)

                self.logger.info(
                    "ENT option %s statistics: correct=%s, incorrect=%s, partial_correct=%s, skiped=%s",
                    ent_option_id,
                    correct,
                    incorrect,
                    partial_correct,
                    skiped,
                )

                total_questions = correct + incorrect + partial_correct + skiped

                if total_questions <= 0:
                    self.logger.debug("No questions for ENT option %s", ent_option_id)
                    return 0.0

                # Расчёт прогресса
                weighted_score = correct * 1.0 + partial_correct * 0.5
                max_possible_score = total_questions * 1.0

                progress = weighted_score / max_possible_score

                self.logger.info(
                    "ENT option %s progress calculation: weighted_score=%s, max_possible_score=%s, progress=%s",
                    ent_option_id,
                    weighted_score,
                    max_possible_score,
                    round(progress, 2),
                )

                return round(progress, 2)
        except Exception as e:
            self.logger.exception(
                "Error getting ENT option progress for option %s: %s",
                ent_option_id,
                str(e),
            )
            return 0.0

    # @cached(strategy=CacheStrategy.USER, ttl=3600, resource="detailed_trainers_progress")
    # def get_detailed_trainers_progress(self, user_id: str) -> list[TrainerProgressDetailDTO]:
    #     """Получить детальный прогресс по всем тренажёрам"""
    #     try:
    #         with self._uow:
    #             trainers = self._uow.trainers.get_all_trainers()

    #             detailed_progress = []

    #             for trainer in trainers:
    #                 progress = self.get_trainer_progress(user_id, trainer.id)
    #                 best_attempt = self._uow.trainer_attempts.get_best_attempt_for_trainer(
    #                     user_id=user_id, trainer_id=trainer.id
    #                 )
    #                 attempt_count = self._has_trainer_attempts(user_id, trainer.id, return_count=True)

    #                 # Получаем количество вопросов
    #                 total_questions = 0
    #                 if hasattr(self._uow.trainers, "count_questions_by_trainer"):
    #                     total_questions = self._uow.trainers.count_questions_by_trainer(trainer.id)

    #                 # Рассчитываем количество правильных вопросов
    #                 correct_questions = 0
    #                 if best_attempt and best_attempt.status == Status.completed:
    #                     statistics = self._uow.trainer_attempts.get_attempt_statistic(best_attempt.id)
    #                     if statistics:
    #                         # Используем правильное имя поля
    #                         correct_questions = getattr(statistics, "correct", 0)
    #                         if hasattr(statistics, "correct_answers"):
    #                             correct_questions = statistics.correct_answers
    #                         elif isinstance(statistics, dict):
    #                             correct_questions = statistics.get("correct", statistics.get("correct_answers", 0))

    #                 detailed_progress.append(
    #                     TrainerProgressDetailDTO(
    #                         trainer_id=trainer.id,
    #                         trainer_name=trainer.name,
    #                         topic_id=trainer.topic_id,
    #                         topic_name=(
    #                             getattr(trainer.topic, "name", "Unknown") if hasattr(trainer, "topic") else "Unknown"
    #                         ),
    #                         progress=progress,
    #                         best_score=getattr(best_attempt, "score", None),
    #                         attempt_count=attempt_count,
    #                         total_questions=total_questions,
    #                         correct_questions=correct_questions,
    #                     )
    #                 )

    #             return detailed_progress
    #     except Exception as e:
    #         self.logger.exception("Error getting detailed trainers progress: %s", str(e))
    #         return []

    # @cached(strategy=CacheStrategy.USER, ttl=3600, resource="detailed_ent_options_progress")
    # def get_detailed_ent_options_progress(self, user_id: str) -> list[EntOptionProgressDetailDTO]:
    #     """Получить детальный прогресс по всем вариантам ЕНТ"""
    #     try:
    #         with self._uow:
    #             # Получаем все варианты ЕНТ
    #             from quiz.converters import to_ent_options_get_service

    #             student_dto = type("StudentDTO", (), {"id": user_id})()
    #             option_params = to_ent_options_get_service(None, student_dto)
    #             ent_options = self._uow.ent_options.get_ents(option_params)

    #             # Если не получилось, используем альтернативный способ
    #             if not ent_options:
    #                 ent_options_result = self._uow.ent_options.get_all_ent_options(page=1, page_size=1000)
    #                 if isinstance(ent_options_result, tuple):
    #                     ent_options, _ = ent_options_result
    #                 else:
    #                     ent_options = ent_options_result

    #             detailed_progress = []

    #             for option in ent_options:
    #                 progress = self.get_ent_option_progress(user_id, option.id)
    #                 best_attempt = self._uow.ent_attempts.get_best_attempt_for_option(
    #                     user_id=user_id, ent_option_id=option.id
    #                 )
    #                 attempt_count = self._has_ent_option_attempts(user_id, option.id, return_count=True)

    #                 # Получаем количество вопросов в варианте
    #                 total_questions = 0
    #                 if hasattr(self._uow.ent_options, "get_ent_questions_count"):
    #                     total_questions = self._uow.ent_options.get_ent_questions_count(option.id)
    #                 elif hasattr(self._uow.ent_options, "count_questions_by_option"):
    #                     total_questions = self._uow.ent_options.count_questions_by_option(option.id)
    #                 elif hasattr(option, "questions"):
    #                     total_questions = len(option.questions) if option.questions else 0

    #                 # Рассчитываем количество правильных вопросов
    #                 correct_questions = 0
    #                 if best_attempt and best_attempt.status == Status.completed:
    #                     statistics = self._uow.ent_attempts.get_attempt_statistic(
    #                         best_attempt.id, getattr(best_attempt, "spend_time", 0)
    #                     )
    #                     if statistics:
    #                         correct_questions = statistics.correct if hasattr(statistics, "correct") else 0

    #                 detailed_progress.append(
    #                     EntOptionProgressDetailDTO(
    #                         option_id=option.id,
    #                         option_number=option.option_number,
    #                         subject_id=option.subject_id,
    #                         subject_name=(
    #                             getattr(option.subject, "name", "Unknown") if hasattr(option, "subject") else "Unknown"
    #                         ),
    #                         progress=progress,
    #                         best_score=getattr(best_attempt, "score", None),
    #                         attempt_count=attempt_count,
    #                         total_questions=total_questions,
    #                         correct_questions=correct_questions,
    #                         last_attempt_at=(getattr(best_attempt, "completed_at", None) if best_attempt else None),
    #                     )
    #                 )

    #             return detailed_progress
    #     except Exception as e:
    #         self.logger.exception("Error getting detailed ENT options progress: %s", str(e))
    #         return []

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="user_progress_overview")
    def get_user_progress_overview(self, user_id: str) -> UserProgressOverviewDTO:
        """
        Получить общий обзор прогресса пользователя по всем направлениям
        """
        try:
            with self._uow:
                # Прогресс по предметам (средний по всем предметам)
                subjects_progress = self._calculate_overall_subjects_progress(user_id)

                # Прогресс по темам (средний по всем темам)
                topics_progress = self._calculate_overall_topics_progress(user_id)

                # Прогресс по тренажёрам
                trainers_summary = self.get_trainers_progress_summary(user_id)

                # Прогресс по ЕНТ
                ent_summary = self.get_ent_options_progress_summary(user_id)

                # Общий прогресс (взвешенное среднее)
                overall_progress = 0.0
                count = 0

                if subjects_progress > 0:
                    overall_progress += subjects_progress
                    count += 1

                if topics_progress > 0:
                    overall_progress += topics_progress
                    count += 1

                if trainers_summary.overall_progress > 0:
                    overall_progress += trainers_summary.overall_progress
                    count += 1

                if ent_summary.overall_progress > 0:
                    overall_progress += ent_summary.overall_progress
                    count += 1

                overall_progress = round(overall_progress / count, 2) if count > 0 else 0.0

                # Общее количество попыток
                total_attempts = self._get_total_attempts_count(user_id)

                # Дней подряд (streak)
                streak_days = self._calculate_streak_days(user_id)

                return UserProgressOverviewDTO(
                    subjects_progress=subjects_progress,
                    topics_progress=topics_progress,
                    trainers_progress=trainers_summary.overall_progress,
                    ent_options_progress=ent_summary.overall_progress,
                    overall_progress=overall_progress,
                    total_attempts=total_attempts,
                    streak_days=streak_days,
                )
        except Exception as e:
            self.logger.exception("Error getting user progress overview: %s", str(e))
            return UserProgressOverviewDTO(
                subjects_progress=0.0,
                topics_progress=0.0,
                trainers_progress=0.0,
                ent_options_progress=0.0,
                overall_progress=0.0,
                total_attempts=0,
                streak_days=0,
            )

    def _calculate_overall_subjects_progress(self, user_id: str) -> float:
        """Рассчитать средний прогресс по всем предметам"""
        try:
            with self._uow:
                subjects = self._uow.subjects.get_all()

                if not subjects:
                    return 0.0

                total_progress = 0.0
                count = 0

                for subject in subjects:
                    try:
                        progress = self.get_subject_progress(user_id, subject.id)
                        total_progress += progress
                        count += 1
                    except Exception as e:
                        self.logger.warning(
                            "Error getting progress for subject %s: %s",
                            subject.id,
                            str(e),
                        )

                return round(total_progress / count, 2) if count > 0 else 0.0
        except Exception as e:
            self.logger.exception("Error calculating overall subjects progress: %s", str(e))
            return 0.0

    def _calculate_overall_topics_progress(self, user_id: str) -> float:
        """Рассчитать средний прогресс по всем темам"""
        try:
            with self._uow:
                topics = self._uow.topics.get_all()

                if not topics:
                    return 0.0

                total_progress = 0.0
                count = 0

                for topic in topics:
                    try:
                        progress = self.get_topic_progress(user_id, topic.id)
                        total_progress += progress
                        count += 1
                    except Exception as e:
                        self.logger.warning("Error getting progress for topic %s: %s", topic.id, str(e))

                return round(total_progress / count, 2) if count > 0 else 0.0
        except Exception as e:
            self.logger.exception("Error calculating overall topics progress: %s", str(e))
            return 0.0

    def _has_trainer_attempts(self, user_id: str, trainer_id: int, return_count: bool = False):
        """Проверить, есть ли попытки у пользователя для тренажёра"""
        try:
            with self._uow:
                if trainer_id is None:
                    return 0 if return_count else False
                if hasattr(self._uow.trainer_attempts, "get_attempt_count"):
                    count = self._uow.trainer_attempts.get_attempt_count(user_id, trainer_id)
                    return count if return_count else count > 0
                else:
                    # Альтернативная проверка
                    best_attempt = self._uow.trainer_attempts.get_best_attempt_for_trainer(
                        user_id=user_id, trainer_id=trainer_id
                    )
                    if return_count:
                        return 1 if best_attempt else 0
                    else:
                        return best_attempt is not None
        except Exception as e:
            self.logger.exception("Error checking trainer attempts: %s", str(e))
            return 0 if return_count else False

    def _has_ent_option_attempts(self, user_id: str, ent_option_id: int, return_count: bool = False):
        """Проверить, есть ли попытки у пользователя для варианта ЕНТ"""
        try:
            with self._uow:
                if hasattr(self._uow.ent_attempts, "get_attempt_count"):
                    count = self._uow.ent_attempts.get_attempt_count(user_id, ent_option_id)
                    return count if return_count else count > 0
                else:
                    # Альтернативная проверка
                    best_attempt = self._uow.ent_attempts.get_best_attempt_for_option(
                        user_id=user_id, ent_option_id=ent_option_id
                    )
                    if return_count:
                        return 1 if best_attempt else 0
                    else:
                        return best_attempt is not None
        except Exception as e:
            self.logger.exception("Error checking ENT option attempts: %s", str(e))
            return 0 if return_count else False

    def _get_total_attempts_count(self, user_id: str) -> int:
        """Получить общее количество всех попыток пользователя"""
        try:
            with self._uow:
                trainer_attempts = 0
                ent_attempts = 0

                if hasattr(self._uow.trainer_attempts, "get_user_total_attempts"):
                    trainer_attempts = self._uow.trainer_attempts.get_user_total_attempts(user_id)

                if hasattr(self._uow.ent_attempts, "get_user_total_attempts"):
                    ent_attempts = self._uow.ent_attempts.get_user_total_attempts(user_id)

                return trainer_attempts + ent_attempts
        except Exception as e:
            self.logger.exception("Error getting total attempts count: %s", str(e))
            return 0

    def _calculate_streak_days(self, user_id: str) -> int:
        """Рассчитать количество дней подряд активности пользователя"""
        try:
            with self._uow:
                # Получаем все даты, когда пользователь делал попытки
                trainer_dates = set()
                ent_dates = set()

                if hasattr(self._uow.trainer_attempts, "get_completed_dates"):
                    trainer_dates = set(self._uow.trainer_attempts.get_completed_dates(user_id))

                if hasattr(self._uow.ent_attempts, "get_completed_dates"):
                    ent_dates = set(self._uow.ent_attempts.get_completed_dates(user_id))

                # Объединяем и убираем дубликаты
                all_dates = trainer_dates.union(ent_dates)

                if not all_dates:
                    return 0

                # Сортируем даты по убыванию
                sorted_dates = sorted(all_dates, reverse=True)

                # Рассчитываем streak
                today = datetime.now(UTC).date()
                streak = 0

                # Если сегодня была активность
                if today in sorted_dates:
                    streak = 1
                    current_date = today - timedelta(days=1)

                    # Проверяем предыдущие дни
                    while current_date in sorted_dates:
                        streak += 1
                        current_date -= timedelta(days=1)
                        if streak > 365:  # Защита от бесконечного цикла
                            break

                return streak
        except Exception as e:
            self.logger.exception("Error calculating streak days: %s", str(e))
            return 0

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="topics_with_progress")
    def get_topics_with_progress(
        self,
        subject_id: int | None = None,
        user_id: str | None = None,
        only_correct: bool = True,
    ) -> list[TopicProgressDTO]:
        """Получить темы с прогрессом (существующий метод)"""
        with self._uow:
            if not user_id:
                return []

            topics_data = self._uow.progress.get_topics_with_progress(
                user_id=user_id,
                subject_id=subject_id,
                only_correct=only_correct,
            )

            result = []
            for topic_data in topics_data:
                # Округляем прогресс до двух знаков
                topic_data["progress"] = round(topic_data.get("progress", 0), 2)
                result.append(TopicProgressDTO(**topic_data))

            return result

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="subjects_with_progress")
    def get_subjects_with_progress(self, user_id: str, only_correct: bool = True) -> list[SubjectProgressDTO]:
        """Получить все предметы с прогрессом (существующий метод)"""
        with self._uow:
            subjects_data = self._uow.progress.get_subjects_with_progress(
                user_id=user_id,
                only_correct=only_correct,
            )

            result = []
            for subject_data in subjects_data:
                # Округляем прогресс до двух знаков
                subject_data["progress"] = round(subject_data.get("progress", 0), 2)
                result.append(SubjectProgressDTO(**subject_data))

            return result

    # def get_trainer_progress_from_all_attempts(self, user_id: str, trainer_id: int) -> float:
    #     """Получить прогресс по тренажёру на основе всех попыток"""
    #     try:
    #         with self._uow:
    #             # Получаем все завершённые попытки
    #             attempts = self._uow.trainer_attempts.get_user_trainer_attempts(user_id=user_id, trainer_id=trainer_id)

    #             completed_attempts = [a for a in attempts if a.status == Status.completed]

    #             if not completed_attempts:
    #                 return 0.0

    #             total_correct = 0
    #             total_questions = 0

    #             for attempt in completed_attempts:
    #                 stats = self._uow.trainer_attempts.get_attempt_statistic(attempt.id)
    #                 if stats:
    #                     correct = getattr(stats, "correct", 0)
    #                     total_q = getattr(stats, "total_questions", 0)

    #                     total_correct += correct
    #                     total_questions += total_q

    #             if total_questions == 0:
    #                 return 0.0

    #             progress = total_correct / total_questions
    #             return round(progress, 2)
    #     except Exception as e:
    #         self.logger.exception("Error calculating progress from all attempts: %s", str(e))
    #         return 0.0

    # def _get_trainer_attempts_details(self, user_id: str, trainer_id: int):
    #     """Получить детали попыток для тренажёра (для отладки)"""
    #     try:
    #         with self._uow:
    #             # Проверяем, есть ли метод get_user_trainer_attempts
    #             if hasattr(self._uow.trainer_attempts, "get_user_trainer_attempts"):
    #                 attempts = self._uow.trainer_attempts.get_user_trainer_attempts(
    #                     user_id=user_id, trainer_id=trainer_id
    #                 )
    #                 self.logger.info("Trainer %s attempts: %s", trainer_id, len(attempts))
    #                 for attempt in attempts:
    #                     self.logger.info(
    #                         "Attempt %s: status=%s, score=%s, created_at=%s",
    #                         attempt.id,
    #                         attempt.status,
    #                         getattr(attempt, "score", "N/A"),
    #                         attempt.created_at,
    #                     )
    #                 return attempts
    #             else:
    #                 # Альтернативный способ
    #                 best_attempt = self._uow.trainer_attempts.get_best_attempt_for_trainer(
    #                     user_id=user_id, trainer_id=trainer_id
    #                 )
    #                 if best_attempt:
    #                     self.logger.info(
    #                         "Trainer %s best attempt: id=%s, status=%s, score=%s",
    #                         trainer_id,
    #                         best_attempt.id,
    #                         best_attempt.status,
    #                         getattr(best_attempt, "score", "N/A"),
    #                     )
    #                 return [best_attempt] if best_attempt else []
    #     except Exception as e:
    #         self.logger.exception("Error getting trainer attempts details: %s", str(e))
    #         return []

    # def _get_ent_option_attempts_details(self, user_id: str, ent_option_id: int):
    #     """Получить детали попыток для ЕНТ варианта (для отладки)"""
    #     try:
    #         with self._uow:
    #             # Проверяем, есть ли метод get_user_ent_option_attempts
    #             if hasattr(self._uow.ent_attempts, "get_user_ent_option_attempts"):
    #                 attempts = self._uow.ent_attempts.get_user_ent_option_attempts(
    #                     user_id=user_id, ent_option_id=ent_option_id
    #                 )
    #                 self.logger.info("ENT option %s attempts: %s", ent_option_id, len(attempts))
    #                 for attempt in attempts:
    #                     self.logger.info(
    #                         "Attempt %s: status=%s, score=%s, created_at=%s",
    #                         attempt.id,
    #                         attempt.status,
    #                         getattr(attempt, "score", "N/A"),
    #                         attempt.created_at,
    #                     )
    #                 return attempts
    #             else:
    #                 # Альтернативный способ
    #                 best_attempt = self._uow.ent_attempts.get_best_attempt_for_option(
    #                     user_id=user_id, ent_option_id=ent_option_id
    #                 )
    #                 if best_attempt:
    #                     self.logger.info(
    #                         "ENT option %s best attempt: id=%s, status=%s, score=%s",
    #                         ent_option_id,
    #                         best_attempt.id,
    #                         best_attempt.status,
    #                         getattr(best_attempt, "score", "N/A"),
    #                     )
    #                 return [best_attempt] if best_attempt else []
    #     except Exception as e:
    #         self.logger.exception("Error getting ENT option attempts details: %s", str(e))
    #         return []

    # def get_trainers_with_progress_by_subject(self, user_id: str, subject_id: int) -> list[dict]:
    #     """Получить тренажёры по предмету с прогрессом"""
    #     try:
    #         with self._uow:
    #             topics = self._uow.topics.get_by_subject_id(subject_id)
    #             result = []

    #             for topic in topics:
    #                 trainers = self._uow.trainers.get_trainers_by_topic_id(topic.id)
    #                 trainers_info = []

    #                 for trainer in trainers:
    #                     progress = self.get_trainer_progress(user_id, trainer.id)

    #                     question_count = 0
    #                     if hasattr(self._uow.trainers, "count_questions_by_trainer"):
    #                         question_count = self._uow.trainers.count_questions_by_trainer(trainer.id)

    #                     answered_question_ids = set()
    #                     if hasattr(self._uow.questions, "get_answered_questions_by_trainer"):
    #                         answered_question_ids = set(
    #                             self._uow.questions.get_answered_questions_by_trainer(
    #                                 student_guid=UUID(user_id), trainer_id=trainer.id
    #                             )
    #                         )

    #                     all_questions = []
    #                     if hasattr(self._uow.questions, "get_by_trainer_id"):
    #                         all_questions = self._uow.questions.get_by_trainer_id(trainer.id)

    #                     question_id_to_index = {q.id: idx for idx, q in enumerate(all_questions)}
    #                     completed_indexes = [
    #                         question_id_to_index[q_id] for q_id in answered_question_ids if q_id in question_id_to_index
    #                     ]

    #                     trainers_info.append(
    #                         {
    #                             "id": trainer.id,
    #                             "name": trainer.name,
    #                             "question_count": question_count,
    #                             "completed_question_indexes": completed_indexes,
    #                             "progress": progress,
    #                         }
    #                     )

    #                 if trainers_info:
    #                     result.append(
    #                         {
    #                             "id": topic.id,
    #                             "name": topic.name,
    #                             "subject_id": topic.subject_id,
    #                             "trainers": trainers_info,
    #                         }
    #                     )

    #             return result

    #     except Exception as e:
    #         self.logger.exception("Error getting trainers with progress by subject: %s", str(e))
    #         return []

    def _invalidate_progress_cache(self, user_id: str, resource: str | None = None):
        """Инвалидировать кеш прогресса"""
        resources = [
            "topic_progress",
            "subject_progress",
            "trainers_progress_summary",
            "ent_options_progress_summary",
            "trainer_progress",
            "ent_option_progress",
            "detailed_trainers_progress",
            "detailed_ent_options_progress",
            "user_progress_overview",
            "topics_with_progress",
            "subjects_with_progress",
        ]

        if resource:
            resources = [resource]

        deleted = self._cache_service.invalidate_by_resources(resources, user_id=user_id)
        self.logger.info("Invalidated progress cache for user %s, deleted %s keys", user_id, deleted)
