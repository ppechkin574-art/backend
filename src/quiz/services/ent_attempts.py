import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from quiz.converters import (
    to_ent_attempt_create_repository,
    to_ent_attempt_service,
    to_service_question,
)
from quiz.dtos.ent_answers import (
    EntAttemptAnswerCreateRepositoryDTO,
    EntAttemptAnswerServiceDTO,
)
from quiz.dtos.ent_attempts import (
    EntAttemptCreateServiceDTO,
    # EntAttemptDetailDTO,
    EntAttemptOptionStatisticServiceDTO,
    EntAttemptServiceDTO,
    EntAttemptStatisticServiceDTO,
    SubjectQuestionsDTO,
)
from quiz.dtos.enums import ExamType, Status
from quiz.dtos.questions import QuestionRepositoryDTO, QuestionServiceDTO
from quiz.exceptions import (
    AlreadyAnswered,
    TrainerAttemptNotExist,
    WrongStudent,
)
from quiz.services.cashback import CashbackService
from quiz.uows.uows import UnitOfWorkTests
from quiz.utils.hint_transform import transform_video_hint
from quiz.utils.init import (
    AnswerCalculator,
    AttemptValidator,
    DateUtils,
    ProgressRecorder,
    # StatisticsCalculator,
    TimeNormalizerService,
    VariantValidator,
)
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class EntAttemptServiceInterface(Protocol):
    def create(
        self,
        attempt_params: EntAttemptCreateServiceDTO,
        locale: str = "ru",
    ) -> EntAttemptServiceDTO:
        raise NotImplementedError

    def answer(
        self, answer: EntAttemptAnswerServiceDTO
    ) -> EntAttemptOptionStatisticServiceDTO:
        raise NotImplementedError

    # def get_answers():
    #     raise NotImplementedError

    # def get_statistic_by_student(self, params: EntStatisticGetServiceDTO) -> EntStatisticServiceDTO:
    #     raise NotImplementedError

    def update_current_question_index(
        self, attempt_id: int, student_guid: UUID, question_index: int
    ) -> dict:
        raise NotImplementedError


class EntAttemptService:
    ENT_BY_SUBJECT_DURATION = 60 * 60  # 60 минут в секундах
    ENT_FULL_EXAM_DURATION = 240 * 60  # 240 минут в секундах

    def __init__(
        self,
        uow: UnitOfWorkTests,
        cache_service: CacheService,
        cashback_service: CashbackService,
    ):
        self._uow = uow
        self._cache_service = cache_service
        self._cashback_service = cashback_service

    def create(
        self,
        attempt_params: EntAttemptCreateServiceDTO,
        locale: str = "ru",
    ) -> EntAttemptServiceDTO:
        logger.info(
            "Starting ENT attempt creation for student: %s, exam_type: %s, option: %s, combination: %s, locale: %s",
            attempt_params.student_guid,
            attempt_params.exam_type,
            attempt_params.ent_option_id,
            attempt_params.subject_combination_id,
            locale,
        )

        logger.info("Received started_at: %s", attempt_params.started_at)
        logger.info("Started_at tzinfo: %s", attempt_params.started_at.tzinfo)

        # Нормализация времени
        # Если пришло naive-время, считаем его локальным и конвертируем в UTC,
        # чтобы избежать смещения и отрицательного spend_time.
        if attempt_params.started_at.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            attempt_params.started_at = attempt_params.started_at.replace(
                tzinfo=local_tz
            )
        attempt_params.started_at = attempt_params.started_at.astimezone(UTC)

        logger.info("Normalized started_at to UTC: %s", attempt_params.started_at)

        # Определяем время на основе типа экзамена
        duration_seconds = (
            self.ENT_FULL_EXAM_DURATION
            if attempt_params.exam_type == ExamType.full_exam
            else self.ENT_BY_SUBJECT_DURATION
        )

        attempt_params.deadline_at = attempt_params.started_at + timedelta(
            seconds=duration_seconds
        )

        with self._uow:
            logger.info("Checking for existing active attempts...")

            # Проверяем наличие активной попытки
            existing = self._get_active_attempt(
                student_guid=attempt_params.student_guid,
                exam_type=attempt_params.exam_type,
                ent_option_id=attempt_params.ent_option_id,
                subject_combination_id=attempt_params.subject_combination_id,
            )

            if existing:
                logger.info(
                    "Found existing active attempt: %s, exam_type: %s",
                    existing.id,
                    existing.exam_type.value,
                )
                resumed = self._return_existing_attempt(existing)
                if locale == "kk":
                    self._localize_questions_kk(resumed)
                return resumed

            # Генерация вопросов для полного экзамена
            precomputed_full_exam_questions = None
            if attempt_params.exam_type == ExamType.full_exam:
                precomputed_full_exam_questions = self._generate_full_exam_questions(
                    attempt_params.subject_combination_id
                )
                question_ids = self._flatten_question_ids(
                    precomputed_full_exam_questions
                )
                attempt_params.full_exam_question_ids = self._serialize_question_ids(
                    question_ids
                )

            # Создание новой попытки
            ent_attempt = self._create_new_attempt(attempt_params)

            # Загрузка вопросов
            if ent_attempt.exam_type.value == "full_exam":
                questions_service = (
                    precomputed_full_exam_questions
                    or self._load_full_exam_questions(ent_attempt)
                )
            else:
                questions_service = self._load_subject_questions(
                    ent_attempt.ent_option_id
                )

            result = to_ent_attempt_service(ent_attempt, questions_service)

            logger.info(
                "ENT attempt creation completed: id=%s, exam_type=%s, questions_count=%s, student=%s",
                result.id,
                ent_attempt.exam_type.value,
                len(questions_service),
                result.student_guid,
            )

            if locale == "kk":
                self._localize_questions_kk(result)

            return result

    def answer(self, answer: EntAttemptAnswerServiceDTO):
        logger.info(
            "Starting ENT answer processing for attempt: %s", answer.ent_attempt_id
        )

        logger.info("Received answer DTO: %s", answer)
        logger.info(
            "Number of questions in answer: %s",
            len(answer.questions) if answer.questions else 0,
        )

        if answer.questions:
            for i, q in enumerate(answer.questions):
                logger.info(
                    "Question %s: id=%s, variants=%s", i + 1, q.question_id, q.variants
                )
        else:
            logger.warning(
                "No questions in answer for attempt %s", answer.ent_attempt_id
            )

        with self._uow:
            # Получаем попытку
            ent_attempt = self._uow.ent_attempts.get_attempt_by_id(
                answer.ent_attempt_id
            )

            logger.info(
                "Found attempt: id=%s, status=%s, started_at=%s",
                ent_attempt.id if ent_attempt else "None",
                ent_attempt.status if ent_attempt else "None",
                ent_attempt.started_at if ent_attempt else "None",
            )

            # Используем AttemptValidator
            AttemptValidator.validate_attempt_exists(
                ent_attempt, answer.ent_attempt_id, answer.student_guid
            )

            if ent_attempt.status == Status.completed:
                logger.warning("Attempt %s already completed", answer.ent_attempt_id)
                raise AlreadyAnswered(
                    f"Attempt {answer.ent_attempt_id} already completed"
                )

            # Текущее время в Астане (GMT+5) как источник end_time
            tz_astana = timezone(timedelta(hours=5))
            now_astana = datetime.now(tz_astana)
            now_utc = now_astana.astimezone(UTC)

            started_at = ent_attempt.started_at
            started_at_utc = (
                started_at.replace(tzinfo=UTC)
                if started_at.tzinfo is None
                else started_at.astimezone(UTC)
            )

            logger.info("Started at (UTC): %s", started_at_utc)

            # Приводим started_at к той же таймзоне (Astana), чтобы избежать naive/aware конфликтов
            tz_astana = timezone(timedelta(hours=5))
            started_at_astana = DateUtils.ensure_timezone(
                started_at, tz_astana
            ).astimezone(tz_astana)

            # Добавляем +2 часа к started_at_astana
            started_at_astana_plus2 = started_at_astana + timedelta(hours=2)

            corrected_spend_time = (
                now_astana - started_at_astana_plus2
            ).total_seconds()
            logger.info(
                "Now (Astana): %s, started_at_astana: %s, started_at_astana_plus2: %s, corrected_spend_time: %s",
                now_astana,
                started_at_astana,
                started_at_astana_plus2,
                corrected_spend_time,
            )

            # Ограничиваем максимальное время экзамена
            max_duration = (
                self.ENT_FULL_EXAM_DURATION
                if ent_attempt.exam_type == ExamType.full_exam
                else self.ENT_BY_SUBJECT_DURATION
            )

            if corrected_spend_time > max_duration:
                logger.warning(
                    "Spend time %s exceeds max duration %s",
                    corrected_spend_time,
                    max_duration,
                )
                corrected_spend_time = max_duration
            elif corrected_spend_time < 1:
                corrected_spend_time = 1  # Минимум 1 секунда

            logger.info("Calculated spend time: %s seconds", corrected_spend_time)

            deadline_exceeded = AttemptValidator.validate_deadline(
                ent_attempt.deadline_at, now_utc
            )

            logger.info("Now UTC: %s", now_utc)
            logger.info("Attempt started_at: %s", ent_attempt.started_at)
            logger.info("Attempt started_at tzinfo: %s", ent_attempt.started_at.tzinfo)

            # Нормализация времени
            time_metrics = TimeNormalizerService.normalize_and_validate_time(
                start_time=ent_attempt.started_at,
                end_time=now_astana,  # end_time строго в GMT+5
                exam_type=ent_attempt.exam_type.value,
                max_allowed_seconds=(
                    self.ENT_FULL_EXAM_DURATION
                    if ent_attempt.exam_type == ExamType.full_exam
                    else self.ENT_BY_SUBJECT_DURATION
                ),
            )

            # Safety clamp: avoid negative or zero spend time due to timezone issues
            if corrected_spend_time <= 0:
                logger.warning(
                    "Corrected spend time is non-positive (%.2f). "
                    "Clamping to 1 second. start_time=%s end_time=%s exam_type=%s",
                    corrected_spend_time,
                    ent_attempt.started_at,
                    now_utc,
                    ent_attempt.exam_type.value,
                )
                corrected_spend_time = 1
                time_metrics["corrected_session_seconds"] = 1
                time_metrics["is_time_corrected"] = True
                time_metrics["correction_reason"] = (
                    time_metrics.get("correction_reason")
                    or "Spend time was non-positive; clamped to 1 second"
                )

            logger.info("Corrected spend time: %s seconds", corrected_spend_time)
            logger.info(
                "Time correction applied: %s", time_metrics["is_time_corrected"]
            )

            # Устанавливаем время завершения
            if time_metrics["is_time_corrected"]:
                corrected_completed_at = ent_attempt.started_at + timedelta(
                    seconds=corrected_spend_time
                )
                ent_attempt.completed_at = corrected_completed_at
            else:
                ent_attempt.completed_at = now_utc

            # Получаем разрешенные ID вопросов
            allowed_question_ids = self._get_allowed_question_ids(ent_attempt)
            logger.info("Allowed question IDs count: %s", len(allowed_question_ids))

            saved_answers_count = 0

            provided_question_ids: set[int] = set()

            # ОБРАБОТКА СЛУЧАЯ ПУСТЫХ ОТВЕТОВ
            if not answer.questions or len(answer.questions) == 0:
                logger.warning(
                    "No questions provided for attempt %s. Creating skipped answers for all %s questions.",
                    answer.ent_attempt_id,
                    len(allowed_question_ids),
                )

                # Создаем пропущенные ответы для всех вопросов
                for qid in allowed_question_ids:
                    answer_create = EntAttemptAnswerCreateRepositoryDTO(
                        ent_attempt_id=ent_attempt.id,
                        variant_id=None,  # Пропущенный вопрос
                    )
                    try:
                        self._uow.ent_attempts.answer(answer_create)
                        saved_answers_count += 1
                        logger.debug("Created skipped answer for question %s", qid)
                    except Exception as e:
                        logger.exception(
                            "Failed to create skipped answer for question %s: %s",
                            qid,
                            e,
                        )
            else:
                # Обработка обычных ответов
                for i, q in enumerate(answer.questions):
                    provided_question_ids.add(q.question_id)
                    logger.info(
                        "Saving question %s/%s: id=%s, variants count: %s",
                        i + 1,
                        len(answer.questions),
                        q.question_id,
                        len(q.variants) if q.variants else 0,
                    )

                    # Проверка принадлежности вопроса (пропускаем для full_exam)
                    if ent_attempt.exam_type != ExamType.full_exam:
                        AttemptValidator.validate_question_belongs_to_attempt(
                            q.question_id,
                            allowed_question_ids,
                            lambda qid: self._uow.ent_options.get_question_by_id(qid),
                        )

                    if q.variants:
                        # Для full_exam используем questions.get_by_id, для by_subject - валидацию
                        if ent_attempt.exam_type == ExamType.full_exam:
                            # Для full_exam получаем вопрос напрямую из questions, без валидации вариантов
                            question_obj = self._uow.questions.get_by_id(q.question_id)

                            # Безопасно получаем варианты
                            try:
                                correct_variant_ids = {
                                    v.id for v in question_obj.variants if v.is_correct
                                }
                                question_type_value = (
                                    question_obj.type.value
                                    if question_obj.type
                                    else "single_choice"
                                )
                            except Exception as e:
                                logger.warning(
                                    "Could not access variants for question %s in full_exam: %s",
                                    q.question_id,
                                    e,
                                )
                                correct_variant_ids = set()
                                question_type_value = "single_choice"
                        else:
                            # Для by_subject - валидация вариантов
                            question_obj = self._validate_ent_variants(
                                q.question_id, q.variants
                            )
                            correct_variant_ids = {
                                v.id for v in question_obj.variants if v.is_correct
                            }
                            question_type_value = question_obj.type.value

                        chosen_variant_ids = set(q.variants)

                        logger.debug("Question type: %s", question_type_value)
                        logger.debug("Chosen variant IDs: %s", chosen_variant_ids)
                        logger.debug("Correct variant IDs: %s", correct_variant_ids)

                        # Если не удалось получить правильные варианты, считаем ответ неправильным
                        if not correct_variant_ids:
                            is_correct = False
                        else:
                            is_correct, _ = AnswerCalculator.calculate_correctness(
                                question_type=question_type_value,
                                chosen_variant_ids=chosen_variant_ids,
                                correct_variant_ids=correct_variant_ids,
                            )

                        logger.debug("Answer is correct: %s", is_correct)

                        # Запись прогресса
                        ProgressRecorder.record_attempt_progress(
                            uow=self._uow,
                            user_id=answer.student_guid,
                            question_id=q.question_id,
                            is_correct=is_correct,
                            attempt_type="ent",
                            attempt_id=answer.ent_attempt_id,
                        )

                    # Сохранение ответов
                    saved_answers_count += self._save_question_answers(
                        ent_attempt.id, q.question_id, q.variants
                    )

                # Обрабатываем вопросы, которые не пришли с фронта — считаем их пропущенными
                missing_question_ids = allowed_question_ids - provided_question_ids
                if missing_question_ids:
                    logger.info(
                        "Marking missing questions as skipped for attempt %s: %s",
                        ent_attempt.id,
                        list(missing_question_ids),
                    )
                    for qid in missing_question_ids:
                        answer_create = EntAttemptAnswerCreateRepositoryDTO(
                            ent_attempt_id=ent_attempt.id,
                            variant_id=None,
                        )
                        try:
                            self._uow.ent_attempts.answer(answer_create)
                            saved_answers_count += 1
                            logger.debug(
                                "Created skipped answer for missing question %s", qid
                            )
                        except Exception as e:
                            logger.exception(
                                "Failed to create skipped answer for missing question %s: %s",
                                qid,
                                e,
                            )

            logger.info("Successfully saved %s answers total", saved_answers_count)

            ent_attempt.status = Status.completed

            attempt_stat = self._uow.ent_attempts.get_attempt_statistic(
                ent_attempt.id, spend_time=int(corrected_spend_time)
            )

            logger.info(
                "Attempt statistic: score=%s, correct=%s, partial_correct=%s,incorrect=%s, skipped=%s, total_questions=%s, spend_time=%s",
                attempt_stat.score,
                attempt_stat.correct,
                attempt_stat.partial_correct,
                attempt_stat.incorrect,
                attempt_stat.skiped,
                attempt_stat.total_questions,
                attempt_stat.spend_time,
            )

            ent_attempt.score = attempt_stat.score
            student_guid = answer.student_guid
            subject_id = None
            if ent_attempt.ent_option_id:
                option = self._uow.ent_options.get_by_id(ent_attempt.ent_option_id)
                if option:
                    subject_id = option.subject_id

            self._uow.ent_attempts.save_attempt_updates(ent_attempt)
            # Business rule (set by operator 23.05.2026): leaderboard
            # points (stars) accrue only from the full ҰБТ — that is the
            # "rated game". A single-subject attempt is training and
            # must NOT bump the leaderboard total. Keeping the score
            # field on the attempt itself untouched (it still gets
            # displayed on the test-result screen for both modes), only
            # the user_points / leaderboard table is gated.
            #
            # award_points_once() does an atomic UPDATE WHERE points_awarded=FALSE
            # and returns True only for the first (winning) call — prevents double
            # award both from repeated submissions and from concurrent race conditions.
            if attempt_stat.score > 0 and ent_attempt.exam_type == ExamType.full_exam:
                if self._uow.ent_attempts.award_points_once(ent_attempt.id):
                    self._uow.user_points.add_points(
                        student_guid,
                        attempt_stat.score,
                        source_type="ent_attempt",
                        source_id=str(ent_attempt.id),
                    )
                else:
                    self._uow.fraud_events.log_event(
                        event_type="repeated_attempt",
                        risk_score=75,
                        user_id=student_guid,
                        reason=(
                            f"Attempt {ent_attempt.id}: award_points_once() blocked "
                            f"duplicate point award (score={attempt_stat.score})"
                        ),
                        endpoint="/user/ents/attempts/answer",
                        method="POST",
                        metadata={"attempt_id": ent_attempt.id, "score": attempt_stat.score},
                    )
            self._uow.commit()
            self._cashback_service.check_and_update(student_guid)

            # score = ent_attempt.score  # уже сохранён в базе
            # if score and score > 0:
            #     self._uow.user_points.add_points(student_guid, score)
            #     self._uow.commit()

            # Формирование результата
            result = EntAttemptStatisticServiceDTO(
                ent_attempt_id=ent_attempt.id,
                score=attempt_stat.score,
                correct=attempt_stat.correct,
                partial_correct=attempt_stat.partial_correct,
                incorrect=attempt_stat.incorrect,
                skiped=attempt_stat.skiped,
                spend_time=int(corrected_spend_time),
                deadline_exceeded=deadline_exceeded,
                completed_at=ent_attempt.completed_at,
                actual_duration_seconds=int(corrected_spend_time),
                allowed_duration_seconds=max_duration,
                time_correction_applied=False,
                time_correction_reason=None,
            )

            logger.info(
                "ENT attempt %s completed: score=%s, correct=%s, incorrect=%s, skipped=%s, total_questions=%s",
                ent_attempt.id,
                attempt_stat.score,
                attempt_stat.correct,
                attempt_stat.incorrect,
                attempt_stat.skiped,
                attempt_stat.total_questions,
            )

            self._invalidate_attempt_cache(
                student_guid,
                ent_attempt.id,
                getattr(ent_attempt, "exam_type", None),
            )

            if subject_id:
                self._cache_service.delete_pattern(
                    f"user:{student_guid}:ent_options:subject_id={subject_id}"
                )

            # Same gating as add_points above — only full_exam can have
            # changed the user_points table, so only that branch needs
            # the cache bust. by_subject never touches user_points →
            # cache stays valid for them.
            if (
                attempt_stat.score > 0
                and ent_attempt.exam_type == ExamType.full_exam
            ):
                self._cache_service.delete_pattern(
                    f"user:{student_guid}:user_points:*"
                )

            # Streak / avg-time / screen-time history all live inside
            # `enhanced_global_statistic` (1h TTL — see statistic.py:40).
            # Without busting it here, the Stats screen renders a stale
            # streak for up to an hour after a finished test, which is
            # the "иногда показывается, иногда нет" symptom (depends on
            # how fresh the user's cache happens to be). Invalidate
            # unconditionally — even a score=0 attempt can change the
            # streak (today counts as a training day).
            self._cache_service.delete_pattern(
                f"user:{student_guid}:enhanced_global_statistic:*"
            )

            return result

    # @cached(strategy=CacheStrategy.USER, ttl=604800, resource="ent_statistic")
    # def get_statistic_by_student(self, params: EntStatisticGetServiceDTO) -> EntStatisticServiceDTO:
    #     with self._uow:
    #         attempts = self._uow.ent_attempts.get_completed_attempts_by_period(
    #             student_guid=params.student_guid,
    #             start_date=datetime.fromtimestamp(params.ts_start),
    #             end_date=datetime.fromtimestamp(params.ts_end),
    #             exam_type=params.exam_type,
    #         )

    #         if not attempts:
    #             logger.info("No completed ENT attempts found for the given period")
    #             empty_overall = EntStatisticOverallDTO(
    #                 total_attempts=0,
    #                 total_correct_answers=0,
    #                 total_questions=0,
    #                 total_spend_time=0,
    #                 avg_correct_percentage=0.0,
    #                 overall_avg_time_per_question=0.0,
    #                 median_time_per_question=0.0,
    #                 avg_score=0.0,
    #                 avg_spend_time=0.0,
    #             )
    #             return EntStatisticServiceDTO(
    #                 overall=empty_overall,
    #                 daily=[],
    #                 streak=0,
    #                 attempts=[],
    #                 exam_type=params.exam_type,
    #             )

    #         # Используем StatisticsCalculator
    #         statistics = StatisticsCalculator.calculate_attempts_statistics(
    #             attempts=attempts,
    #             get_attempt_stats_func=lambda attempt_id: self._uow.ent_attempts.get_attempt_statistic(
    #                 attempt_id, None
    #             ),
    #             get_question_times_func=[],
    #             exam_type=("ent_full_exam" if params.exam_type == ExamType.full_exam else "ent_by_subject"),
    #             timezone_offset_hours=0,
    #         )

    #         # Рассчитываем общую статистику
    #         overall_data = StatisticsCalculator.calculate_overall_statistics(statistics, include_partial=True)

    #         # Рассчитываем дневную статистику
    #         daily_data = StatisticsCalculator.calculate_daily_statistics(
    #             statistics["daily_stats"], include_partial=True
    #         )

    #         # Рассчитываем streak
    #         streak = StreakCalculator.calculate_streak(
    #             activity_dates=self._uow.ent_attempts.get_completed_dates(params.student_guid),
    #             timezone_offset_hours=0,
    #             include_today=True,
    #         )

    #         # Формируем детали попыток
    #         attempts_details = []
    #         for attempt_stat in statistics["all_attempt_stats"]:
    #             attempt = next((a for a in attempts if a.id == attempt_stat["attempt_id"]), None)
    #             option_number = getattr(attempt.options, "option_number", 0) if attempt else 0

    #             attempts_details.append(
    #                 EntAttemptDetailDTO(
    #                     attempt_id=attempt_stat["attempt_id"],
    #                     option_number=option_number,
    #                     completed_at=attempt_stat["completed_at"],
    #                     correct_answers=attempt_stat["correct_answers"],
    #                     total_questions=attempt_stat["total_questions"],
    #                     spend_time=attempt_stat["spend_time"],
    #                     score=attempt_stat["score"],
    #                     correct_percentage=attempt_stat["correct_percentage"],
    #                     avg_time_per_question=attempt_stat["avg_time_per_question"],
    #                     time_correction_applied=attempt_stat["time_correction_applied"],
    #                 )
    #             )

    #         # Создаем TimeMetricsDTO
    #         time_metrics = TimeMetricsDTO(
    #             total_session_seconds=statistics["total_session_seconds"],
    #             corrected_session_seconds=statistics["total_active_seconds"],
    #             efficiency_ratio=overall_data.get("efficiency_ratio"),
    #         )

    #         overall_stats = EntStatisticOverallDTO(
    #             total_attempts=overall_data["total_attempts"],
    #             total_correct_answers=overall_data["total_correct_answers"],
    #             total_questions=overall_data["total_questions"],
    #             total_spend_time=overall_data["total_spend_time"],
    #             avg_correct_percentage=overall_data["avg_correct_percentage"],
    #             overall_avg_time_per_question=overall_data["overall_avg_time_per_question"],
    #             median_time_per_question=overall_data["median_time_per_question"],
    #             avg_score=overall_data["avg_score"],
    #             avg_spend_time=overall_data["avg_spend_time"],
    #             time_metrics=time_metrics,
    #         )

    #         daily_stats = [
    #             EntStatisticDailyDTO(
    #                 date=daily["date"],
    #                 total_attempts=daily["total_attempts"],
    #                 total_correct_answers=daily["total_correct_answers"],
    #                 total_questions=daily["total_questions"],
    #                 total_spend_time=daily["total_spend_time"],
    #                 avg_correct_percentage=daily["avg_correct_percentage"],
    #                 overall_avg_time_per_question=daily["overall_avg_time_per_question"],
    #                 median_time_per_question=daily["median_time_per_question"],
    #                 avg_score=daily["avg_score"],
    #                 avg_spend_time=daily["avg_spend_time"],
    #             )
    #             for daily in daily_data
    #         ]

    #         return EntStatisticServiceDTO(
    #             overall=overall_stats,
    #             daily=daily_stats,
    #             streak=streak,
    #             attempts=attempts_details,
    #             exam_type=params.exam_type,
    #         )

    # Вспомогательные методы (с использованием утилит)
    def _get_active_attempt(
        self, student_guid, exam_type, ent_option_id=None, subject_combination_id=None
    ):
        """Получить активную попытку"""
        if exam_type == ExamType.full_exam:
            return self._uow.ent_attempts.get_active_full_exam_for_student(
                student_guid=student_guid,
                subject_combination_id=subject_combination_id,
            )
        else:
            return self._uow.ent_attempts.get_active_for_student(
                student_guid=student_guid,
                ent_option_id=ent_option_id,
            )

    def _return_existing_attempt(self, existing):
        """Вернуть существующую попытку"""
        if existing.exam_type.value == "full_exam":
            questions_service = self._load_full_exam_questions(existing)
        else:
            questions_service = self._load_subject_questions(existing.ent_option_id)

        result = to_ent_attempt_service(existing, questions_service)
        logger.info(
            "Returning existing attempt: %s with question_count=%s",
            result.id,
            result.question_count,
        )
        return result

    def _create_new_attempt(self, attempt_params):
        """Создать новую попытку"""
        try:
            logger.info("Creating new ENT attempt...")
            ent_attempt = self._uow.ent_attempts.create(
                to_ent_attempt_create_repository(attempt_params)
            )
            logger.info("Created new ENT attempt with ID: %s", ent_attempt.id)
            self._uow.commit()
            return ent_attempt
        except IntegrityError as e:
            logger.warning("IntegrityError during attempt creation: %s", e)
            # Обработка race condition
            existing = self._get_active_attempt(
                student_guid=attempt_params.student_guid,
                exam_type=attempt_params.exam_type,
                ent_option_id=attempt_params.ent_option_id,
                subject_combination_id=attempt_params.subject_combination_id,
            )
            if existing:
                return self._return_existing_attempt(existing)
            else:
                raise

    def _localize_questions_kk(self, attempt_dto: EntAttemptServiceDTO) -> None:
        """Splice `question_text_kk` / `hint_text_kk` / `variant_text_kk`
        into each question's blocks for `attempt_dto.questions` (in-place).

        Why this lives on the create path
        ---------------------------------
        `create-full-exam` (and `create` for single-subject) returns the
        question list inline. The result is consumed by the Flutter test
        screen and persists for the entire attempt — re-fetches happen
        only via `get_attempt_detail` (which has its own kk wiring).
        Without this hook the Kazakh user sees Russian text throughout
        the test even after the pilot's data import landed.

        Safety
        ------
        * No-op when no question / variant carries a kk string (e.g.
          Physics / non-Math subjects in the Phase 7b pilot scope).
        * Two batched SELECTs (questions + variants) per attempt — cheap
          relative to the question-bank join that already happened.
        * Hint blocks are spliced only when `transform_video_hint` left
          something to splice into.
        """
        from sqlalchemy import bindparam, text

        from quiz.dtos.hint import localize_hint_blocks_with_kk_text
        from quiz.dtos.questions import localize_blocks_with_kk_text

        questions_field = attempt_dto.questions
        if not questions_field:
            return

        is_grouped = isinstance(questions_field[0], SubjectQuestionsDTO)
        if is_grouped:
            flat_questions: list[QuestionServiceDTO] = [
                q for group in questions_field for q in group.questions
            ]
        else:
            flat_questions = list(questions_field)

        question_ids = [q.id for q in flat_questions if q.id is not None]
        if not question_ids:
            return

        # 1) Question + hint kk splice
        q_stmt = text(
            "SELECT id, question_text_kk, hint_text_kk "
            "FROM questions WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        q_rows = self._uow.session.execute(
            q_stmt, {"ids": question_ids}
        ).fetchall()
        q_kk: dict[int, tuple[str | None, str | None]] = {
            row[0]: (row[1], row[2]) for row in q_rows
        }

        # 2) Variant kk splice — one batched SELECT keyed by variant.id
        variant_ids: list[int] = []
        for q in flat_questions:
            for v in q.variants or []:
                if v.id is not None:
                    variant_ids.append(v.id)

        v_kk: dict[int, str] = {}
        if variant_ids:
            v_stmt = text(
                "SELECT id, variant_text_kk "
                "FROM variants WHERE id IN :ids "
                "AND variant_text_kk IS NOT NULL"
            ).bindparams(bindparam("ids", expanding=True))
            for row in self._uow.session.execute(
                v_stmt, {"ids": variant_ids}
            ).fetchall():
                v_kk[row[0]] = row[1]

        for q in flat_questions:
            if q.id is not None:
                kk = q_kk.get(q.id)
                if kk:
                    q_text_kk, hint_text_kk = kk
                    if q_text_kk:
                        q.blocks = localize_blocks_with_kk_text(q.blocks, q_text_kk)
                    if (
                        hint_text_kk
                        and q.hint is not None
                        and getattr(q.hint, "blocks", None)
                    ):
                        q.hint.blocks = localize_hint_blocks_with_kk_text(
                            q.hint.blocks, hint_text_kk
                        )
            for v in q.variants or []:
                if v.id is None:
                    continue
                kk_str = v_kk.get(v.id)
                if kk_str:
                    v.blocks = localize_blocks_with_kk_text(v.blocks, kk_str)

    def _load_subject_questions(self, ent_option_id):
        """Загрузить вопросы по предмету"""
        questions_repo = self._uow.ent_options.get_option_questions(
            ent_option_id=ent_option_id
        )
        return [to_service_question(q) for q in questions_repo]

    def _validate_ent_variants(self, question_id: int, variant_ids: list[int]):
        """Проверить варианты ЕНТ"""
        with self._uow:
            question = self._uow.ent_options.get_question_by_id(question_id)

            if not question:
                raise ValueError(f"Question {question_id} not found in ENТ")

            logger.info("Validating question %s: type=%s", question.id, question.type)
            logger.info("Question has %s variants", len(question.variants))

            for i, v in enumerate(question.variants):
                logger.info(
                    "Variant %s: id=%s, is_correct=%s",
                    i + 1,
                    v.id,
                    getattr(v, "is_correct", "NO ATTR"),
                )

            valid_variant_ids = VariantValidator.get_valid_variant_ids(question)
            VariantValidator.validate_variants_belong_to_question(
                question_id=question_id,
                variant_ids=variant_ids,
                valid_variant_ids=valid_variant_ids,
                # question_repo=question,
            )

            return question

    def _save_question_answers(
        self, attempt_id: int, question_id: int, variants: list
    ) -> int:
        """Сохранить ответы на вопрос"""
        saved = 0

        logger.debug(
            "Saving answers for question %s: variants=%s", question_id, variants
        )

        if not variants or len(variants) == 0:
            answer_create = EntAttemptAnswerCreateRepositoryDTO(
                ent_attempt_id=attempt_id, variant_id=None
            )
            try:
                self._uow.ent_attempts.answer(answer_create)
                saved += 1
                logger.debug("Created skipped answer for question %s", question_id)
            except Exception as e:
                logger.exception(
                    "Failed to save skipped answer: question=%s, error=%s",
                    question_id,
                    e,
                )
                raise
        else:
            for variant_id in variants:
                try:
                    answer_create = EntAttemptAnswerCreateRepositoryDTO(
                        ent_attempt_id=attempt_id,
                        variant_id=variant_id,
                    )
                    self._uow.ent_attempts.answer(answer_create)
                    self._uow.commit()
                    saved += 1
                    logger.debug(
                        "Saved answer for question=%s, variant=%s",
                        question_id,
                        variant_id,
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to save answer: question=%s, variant=%s, error=%s",
                        question_id,
                        variant_id,
                        e,
                    )
                    raise

        return saved

    # _ensure_question_service_dto, _extract_subject_info, _extract_topic_name)
    def _generate_full_exam_questions(self, subject_combination_id: int | None):
        """
        Генерирует вопросы для полноценного экзамена из 4 предметов:
        - История Казахстана: 20 вопросов
        - Грамотность чтения: 10 вопросов
        - Математическая грамотность: 10 вопросов
        - 2 профильных предмета из выбранной связки: по 40 вопросов каждый

        Итого: 120 вопросов (имитация настоящего ЕНТ)
        """
        import random

        from quiz.models.edu_content import Subject

        logger.info(
            "Generating full exam questions for combination: %s",
            subject_combination_id,
        )

        if not subject_combination_id:
            raise ValueError("subject_combination_id is required for full_exam type")

        # Лимиты вопросов для каждого предмета (имитация настоящего ЕНТ)
        QUESTION_LIMITS = {
            "История Казахстана": 20,
            "Грамотность чтения": 10,
            "Математическая грамотность": 10,
            # Все профильные предметы по умолчанию: 40 вопросов
        }
        DEFAULT_SPECIALIZED_LIMIT = 40

        # НЕ открываем новый контекст! Используем уже существующий из метода create()
        # Получаем связку предметов
        from quiz.models.ent import EntSubjectCombination

        combination = (
            self._uow.session.query(EntSubjectCombination)
            .filter_by(id=subject_combination_id)
            .first()
        )

        if not combination:
            raise ValueError(f"Subject combination {subject_combination_id} not found")

        # Находим обязательные предметы по именам
        history_kz = (
            self._uow.session.query(Subject)
            .filter(Subject.name == "История Казахстана")
            .first()
        )
        reading_lit = (
            self._uow.session.query(Subject)
            .filter(Subject.name == "Грамотность чтения")
            .first()
        )
        math_lit = (
            self._uow.session.query(Subject)
            .filter(Subject.name == "Математическая грамотность")
            .first()
        )
        mandatory_subject_ids = []
        if history_kz:
            mandatory_subject_ids.append(history_kz.id)
        if reading_lit:
            mandatory_subject_ids.append(reading_lit.id)
        if math_lit:
            mandatory_subject_ids.append(math_lit.id)
        logger.info("Found mandatory subjects: %s", mandatory_subject_ids)

        # ID профильных предметов из связки
        specialized_subject_ids = [
            combination.specialized_subject_1_id,
            combination.specialized_subject_2_id,
        ]

        all_subject_ids = mandatory_subject_ids + specialized_subject_ids

        logger.info("Full exam subjects: %s", all_subject_ids)

        # Собираем вопросы по предметам (группируем)
        from quiz.dtos.ent_attempts import SubjectQuestionsDTO

        subject_groups = []
        total_questions = 0

        for subject_id in all_subject_ids:
            # Получаем предмет
            subject = (
                self._uow.session.query(Subject)
                .filter(Subject.id == subject_id)
                .first()
            )
            if not subject:
                continue

            # Определяем лимит вопросов для данного предмета
            question_limit = QUESTION_LIMITS.get(
                subject.name, DEFAULT_SPECIALIZED_LIMIT
            )

            # Получаем все вопросы по предмету
            questions_repo = self._uow.questions.get_questions_by_subject(subject_id)
            questions_service = [to_service_question(q) for q in questions_repo]

            # Перемешиваем вопросы ВНУТРИ предмета
            random.shuffle(questions_service)

            # Ограничиваем количество вопросов согласно лимиту
            questions_service = questions_service[:question_limit]

            logger.info(
                "Subject '%s': selected %s questions (limit: %s)",
                subject.name,
                len(questions_service),
                question_limit,
            )

            # Создаем группу для этого предмета
            subject_group = SubjectQuestionsDTO(
                subject_id=subject.id,
                subject_name=subject.name,
                questions=questions_service,
            )
            subject_groups.append(subject_group)
            total_questions += len(questions_service)

        logger.info(
            "Generated %s questions for full exam grouped by %s subjects",
            total_questions,
            len(subject_groups),
        )

        return subject_groups

    def _load_full_exam_questions(self, attempt) -> list[SubjectQuestionsDTO]:
        """Загружает сохранённый набор вопросов для полноценного экзамена"""
        question_ids = self._parse_question_ids(
            getattr(attempt, "full_exam_question_ids", None)
        )

        if not question_ids:
            logger.info(
                "Attempt %s has no stored question ids, regenerating question set",
                attempt.id,
            )
            subject_groups = self._generate_full_exam_questions(
                getattr(attempt, "subject_combination_id", None)
            )
            question_ids = self._flatten_question_ids(subject_groups)
            questions_csv = self._serialize_question_ids(question_ids)
            self._uow.ent_attempts.update_full_exam_question_ids(
                attempt.id, questions_csv
            )
            attempt.full_exam_question_ids = questions_csv
            return subject_groups

        question_repos = self._uow.questions.get_questions_by_ids(question_ids)
        if not question_repos:
            logger.warning(
                "Stored question ids for attempt %s could not be loaded from DB",
                attempt.id,
            )
            subject_groups = self._generate_full_exam_questions(
                getattr(attempt, "subject_combination_id", None)
            )
            question_ids = self._flatten_question_ids(subject_groups)
            questions_csv = self._serialize_question_ids(question_ids)
            self._uow.ent_attempts.update_full_exam_question_ids(
                attempt.id, questions_csv
            )
            attempt.full_exam_question_ids = questions_csv
            return subject_groups

        question_map = {q.id: q for q in question_repos}
        grouped_questions = []
        current_group: SubjectQuestionsDTO | None = None
        current_subject_id = None

        for question_id in question_ids:
            question_repo = question_map.get(question_id)
            if not question_repo:
                continue
            subject_id = question_repo.subject_id or 0
            subject_name = question_repo.subject_name or "Unknown"

            if current_group is None or current_subject_id != subject_id:
                current_group = SubjectQuestionsDTO(
                    subject_id=subject_id,
                    subject_name=subject_name,
                    questions=[],
                )
                grouped_questions.append(current_group)
                current_subject_id = subject_id

            current_group.questions.append(to_service_question(question_repo))

        return grouped_questions

    @staticmethod
    def _flatten_question_ids(subject_groups: list[SubjectQuestionsDTO]) -> list[int]:
        ids: list[int] = []
        for group in subject_groups:
            ids.extend([question.id for question in group.questions])
        return ids

    @staticmethod
    def _serialize_question_ids(question_ids: list[int]) -> str:
        return ",".join(str(q_id) for q_id in question_ids)

    @staticmethod
    def _parse_question_ids(value: str | None) -> list[int]:
        if not value:
            return []
        ids: list[int] = []
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue
        return ids

    def _get_allowed_question_ids(self, attempt) -> set[int]:
        """Вернёт множество ID вопросов, которые принадлежат попытке"""
        if attempt.exam_type == ExamType.full_exam:
            question_ids = self._parse_question_ids(
                getattr(attempt, "full_exam_question_ids", None)
            )
            if not question_ids:
                subject_groups = self._load_full_exam_questions(attempt)
                question_ids = self._flatten_question_ids(subject_groups)
            return set(question_ids)

        if attempt.ent_option_id:
            option_question_ids = self._uow.ent_options.get_questions_ids(
                attempt.ent_option_id
            )
            return set(option_question_ids)

        return set()

    def update_current_question_index(
        self, attempt_id: int, student_guid: UUID, question_index: int
    ) -> dict:
        """Обновить текущую позицию вопроса в попытке"""
        logger.info(
            "Updating current question index for attempt %s to %s",
            attempt_id,
            question_index,
        )

        with self._uow:
            attempt = self._uow.ent_attempts.get_attempt_by_id(attempt_id)

            if not attempt:
                raise TrainerAttemptNotExist(f"Attempt {attempt_id} not found")

            if str(attempt.student_guid) != str(student_guid):
                raise WrongStudent("Attempt doesn't belong to student")

            if attempt.status != Status.in_progress:
                raise AlreadyAnswered(
                    f"Cannot update position - attempt is {attempt.status}"
                )

            # Обновляем текущую позицию
            attempt.current_question_index = question_index
            self._uow.ent_attempts.save_attempt_updates(attempt)

            logger.info(
                "Updated current question index for attempt %s to %s",
                attempt_id,
                question_index,
            )

            return {
                "attempt_id": attempt.id,
                "current_question_index": question_index,
                "status": "success",
            }

    @cached(strategy=CacheStrategy.USER, ttl=604800, resource="ent_attempts_history")
    def get_attempts_history(
        self, student_guid: UUID, limit: int | None = None
    ) -> list:
        """Получить историю попыток студента"""
        from quiz.dtos.ent_attempts import (
            EntAttemptBySubjectHistoryDTO,
            EntAttemptFullExamHistoryDTO,
        )

        logger.info(
            "Getting attempts history for student %s, limit=%s", student_guid, limit
        )

        with self._uow:
            attempts = self._uow.ent_attempts.get_all_attempts_for_student(
                student_guid, limit
            )

            history = []
            for attempt in attempts:
                # Получаем статистику если попытка завершена
                stats = None
                if attempt.status == Status.completed and attempt.completed_at:
                    try:
                        spend_time = int(
                            (attempt.completed_at - attempt.started_at).total_seconds()
                        )
                        stats = self._uow.ent_attempts.get_attempt_statistic(
                            attempt.id, spend_time
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to get stats for attempt %s: %s", attempt.id, e
                        )

                # Общие поля
                common_fields = {
                    "id": attempt.id,
                    "guid": attempt.guid,
                    "status": attempt.status,
                    "score": attempt.score,
                    "started_at": attempt.started_at,
                    "completed_at": attempt.completed_at,
                    "deadline_at": attempt.deadline_at,
                    "total_questions": (
                        stats.correct
                        + stats.incorrect
                        + stats.partial_correct
                        + stats.skiped
                        if stats
                        else None
                    ),
                    "correct_answers": stats.correct if stats else None,
                    "incorrect_answers": stats.incorrect if stats else None,
                    "skipped_answers": stats.skiped if stats else None,
                    "spend_time_seconds": stats.spend_time if stats else None,
                }

                # Создаем правильный тип в зависимости от exam_type
                if attempt.exam_type.value == "by_subject":
                    history.append(
                        EntAttemptBySubjectHistoryDTO(
                            **common_fields,
                            exam_type=ExamType.by_subject,
                            ent_option_id=attempt.ent_option_id or 0,
                            subject_id=(
                                attempt.options.subject_id if attempt.options else 0
                            ),
                            subject_name=(
                                attempt.options.subject.name
                                if attempt.options and attempt.options.subject
                                else "Unknown"
                            ),
                            option_number=(
                                attempt.options.option_number if attempt.options else 0
                            ),
                        )
                    )
                else:  # full_exam
                    history.append(
                        EntAttemptFullExamHistoryDTO(
                            **common_fields,
                            exam_type=ExamType.full_exam,
                            subject_combination_id=attempt.subject_combination_id or 0,
                            subject_combination_name=(
                                attempt.subject_combination.name
                                if attempt.subject_combination
                                else "Unknown"
                            ),
                        )
                    )

            logger.info("Found %s attempts for student %s", len(history), student_guid)
            return history

    # NB: not @cached — Phase 7b adds a `locale` parameter and the existing
    # USER strategy doesn't key on it, so a cached `ru` response would leak
    # into `kk` requests for the same student.  Disabling the cache for this
    # one endpoint is acceptable in the pilot — the screen is only opened
    # after a test completes, not on every poll, so it's already cold-pathy.
    # Future improvement: extend `@cached` with explicit cache_key_fields.
    def get_attempt_detail(self, attempt_id: int, student_guid: UUID, locale: str = "ru"):
        """Получить детальную информацию о попытке с ответами"""
        from quiz.dtos.ent_attempts import (
            EntAttemptBySubjectDetailDTO,
            EntAttemptFullExamDetailDTO,
            SubjectQuestionsWithAnswersDTO,
        )

        logger.info(
            "Getting attempt detail for attempt_id=%s, student=%s",
            attempt_id,
            student_guid,
        )

        with self._uow:
            # Получаем попытку
            attempt = self._uow.ent_attempts.get_attempt_with_answers(
                attempt_id, student_guid
            )

            if not attempt:
                raise TrainerAttemptNotExist(
                    f"Attempt {attempt_id} not found for student {student_guid}"
                )

            # Проверяем, что попытка завершена
            if attempt.status == Status.in_progress:
                raise AlreadyAnswered(
                    f"Cannot view detailed statistics for attempt {attempt_id} - test is still in progress. "
                    f"Please complete the test first."
                )

            # Получаем статистику
            spend_time = 0
            if attempt.completed_at:
                spend_time = int(
                    (attempt.completed_at - attempt.started_at).total_seconds()
                )

            stats = self._uow.ent_attempts.get_attempt_statistic(attempt.id, spend_time)

            # Получаем ответы пользователя
            user_answers = self._uow.ent_attempts.get_attempt_answers_with_questions(
                attempt.id
            )

            # Получаем все вопросы попытки
            if attempt.exam_type.value == "by_subject":
                # Для by_subject получаем вопросы из ent_option
                questions_repo = self._uow.ent_options.get_option_questions(
                    attempt.ent_option_id
                )
            else:
                # Для full_exam восстанавливаем сохранённый набор вопросов
                questions_repo = self._load_full_exam_questions(attempt)

            # Создаем мапу ответов пользователя: question_id -> [variant_ids]
            user_answers_map = {}
            for answer in user_answers:
                if answer.variant_id:
                    question_id = answer.variant.question_id
                    if question_id not in user_answers_map:
                        user_answers_map[question_id] = []
                    user_answers_map[question_id].append(answer.variant_id)

            logger.info("User answers map: %s", user_answers_map)

            # Формируем общие поля
            common_fields = {
                "id": attempt.id,
                "guid": attempt.guid,
                "status": attempt.status,
                "score": attempt.score,
                "started_at": attempt.started_at,
                "completed_at": attempt.completed_at,
                "deadline_at": attempt.deadline_at,
                "total_questions": stats.correct
                + stats.incorrect
                + stats.partial_correct
                + stats.skiped,
                "correct_answers": stats.correct,
                "incorrect_answers": stats.incorrect,
                "skipped_answers": stats.skiped,
                "partial_correct_answers": stats.partial_correct,
                "spend_time_seconds": stats.spend_time,
            }

            # Возвращаем правильный тип в зависимости от exam_type
            if attempt.exam_type.value == "by_subject":
                # Для by_subject - плоский список
                default_subject_name = None
                if attempt.options and attempt.options.subject:
                    default_subject_name = attempt.options.subject.name

                questions_with_answers = self._build_questions_with_answers(
                    questions_repo,
                    user_answers_map,
                    default_subject_name=default_subject_name,
                    locale=locale,
                )

                return EntAttemptBySubjectDetailDTO(
                    **common_fields,
                    exam_type=ExamType.by_subject,
                    ent_option_id=attempt.ent_option_id,
                    subject_id=attempt.options.subject_id if attempt.options else 0,
                    subject_name=(
                        attempt.options.subject.name
                        if attempt.options and attempt.options.subject
                        else "Unknown"
                    ),
                    option_number=(
                        attempt.options.option_number if attempt.options else 0
                    ),
                    questions=questions_with_answers,
                )
            else:
                # Для full_exam - группировка по предметам
                questions_by_subject = []
                for subject_group in questions_repo:
                    subject_questions = self._build_questions_with_answers(
                        subject_group.questions,
                        user_answers_map,
                        default_subject_name=subject_group.subject_name,
                        locale=locale,
                    )
                    questions_by_subject.append(
                        SubjectQuestionsWithAnswersDTO(
                            subject_id=subject_group.subject_id,
                            subject_name=subject_group.subject_name,
                            questions=subject_questions,
                        )
                    )

                return EntAttemptFullExamDetailDTO(
                    **common_fields,
                    exam_type=ExamType.full_exam,
                    subject_combination_id=attempt.subject_combination_id,
                    subject_combination_name=(
                        attempt.subject_combination.name
                        if attempt.subject_combination
                        else "Unknown"
                    ),
                    questions=questions_by_subject,
                )

    def _build_questions_with_answers(
        self,
        questions,
        user_answers_map: dict,
        default_subject_name: str | None = None,
        locale: str = "ru",
    ) -> list:
        """Построить список вопросов с информацией об ответах.

        Phase 7b — when `locale="kk"`, splice the cached Kazakh
        `question_text_kk` / `hint_text_kk` columns into the rendered
        block list via the dedicated helpers.  Fully transparent when
        the kk columns are NULL (e.g. subjects other than Математика
        in the pilot) — the helpers no-op and return the original
        blocks list unchanged.
        """
        from sqlalchemy import bindparam, text as sql_text

        from quiz.dtos.ent_attempts import QuestionWithAnswerDTO, VariantWithAnswerDTO
        from quiz.dtos.hint import localize_hint_blocks_with_kk_text
        from quiz.dtos.questions import localize_blocks_with_kk_text

        # Phase 7b — single batched SELECT for variant_text_kk across all
        # variants in this attempt. Done once up-front so we don't fire
        # one SELECT per variant inside the loop. No-op when locale != kk.
        variant_kk_map: dict[int, str] = {}
        if locale == "kk":
            variant_ids: list[int] = []
            for q_obj in questions:
                q_dto_preview = self._ensure_question_service_dto(q_obj)
                variant_ids.extend(
                    v.id for v in q_dto_preview.variants if v.id is not None
                )
            if variant_ids:
                v_stmt = sql_text(
                    "SELECT id, variant_text_kk FROM variants "
                    "WHERE id IN :ids AND variant_text_kk IS NOT NULL"
                ).bindparams(bindparam("ids", expanding=True))
                for row in self._uow.session.execute(
                    v_stmt, {"ids": variant_ids}
                ).fetchall():
                    variant_kk_map[row[0]] = row[1]

        questions_with_answers = []

        for idx, question_obj in enumerate(questions):
            question_dto = self._ensure_question_service_dto(question_obj)
            user_variant_ids = user_answers_map.get(question_dto.id, [])

            variants = []
            correct_variant_ids = set()
            for variant in question_dto.variants:
                v_blocks = variant.blocks
                if locale == "kk":
                    kk_str = variant_kk_map.get(variant.id)
                    if kk_str:
                        v_blocks = localize_blocks_with_kk_text(v_blocks, kk_str)
                variants.append(
                    VariantWithAnswerDTO(
                        id=variant.id,
                        blocks=v_blocks,
                        is_correct=variant.is_correct,
                        weight=variant.weight,
                        user_selected=variant.id in user_variant_ids,
                    )
                )
                if variant.is_correct:
                    correct_variant_ids.add(variant.id)

            is_correct = None
            if user_variant_ids:
                user_set = set(user_variant_ids)
                is_correct = user_set == correct_variant_ids

            # Transform hint blocks for video type
            transformed_hint = transform_video_hint(question_dto.hint)

            # Phase 7b — splice cached Kazakh text into blocks/hint when
            # the user's locale is `kk` and the columns are populated.
            # Helpers no-op when their respective `_kk` column is NULL,
            # so this is safe to call unconditionally for kk-locale
            # requests across subjects whose data hasn't been imported.
            question_blocks = question_dto.blocks
            if locale == "kk":
                question_text_kk = getattr(question_obj, "question_text_kk", None)
                if question_text_kk is None and hasattr(question_obj, "question"):
                    # `question_obj` is a join wrapper (e.g. EntOptionQuestion)
                    # — peek at the inner `.question` row for the column.
                    question_text_kk = getattr(
                        question_obj.question, "question_text_kk", None
                    )
                question_blocks = localize_blocks_with_kk_text(
                    question_blocks, question_text_kk
                )

                hint_text_kk = getattr(question_obj, "hint_text_kk", None)
                if hint_text_kk is None and hasattr(question_obj, "question"):
                    hint_text_kk = getattr(
                        question_obj.question, "hint_text_kk", None
                    )
                if transformed_hint is not None and hint_text_kk:
                    transformed_hint = transformed_hint.model_copy(
                        update={
                            "blocks": localize_hint_blocks_with_kk_text(
                                transformed_hint.blocks, hint_text_kk
                            )
                        }
                    )

            questions_with_answers.append(
                QuestionWithAnswerDTO(
                    id=question_dto.id,
                    guid=question_dto.guid,
                    topic_id=question_dto.topic_id,
                    subject_id=question_dto.subject_id or 0,
                    difficulty=question_dto.difficulty,
                    type=question_dto.type,
                    blocks=question_blocks,
                    hint=transformed_hint,
                    variants=variants,
                    question_number=idx + 1,
                    is_correct=is_correct,
                    subject_name=self._extract_subject_name(question_obj)
                    or default_subject_name
                    or "Unknown",
                    topic_name=self._extract_topic_name(question_obj),
                    task_description_ru=getattr(question_obj, "task_description_ru", None),
                    task_description_kk=getattr(question_obj, "task_description_kk", None),
                    question_translation_ru=getattr(question_obj, "question_translation_ru", None),
                    question_translation_kk=getattr(question_obj, "question_translation_kk", None),
                    explanation_ru=getattr(question_obj, "explanation_ru", None),
                    explanation_kk=getattr(question_obj, "explanation_kk", None),
                )
            )

        return questions_with_answers

    def _ensure_question_service_dto(self, question_obj) -> QuestionServiceDTO:
        """Привести вопрос к QuestionServiceDTO независимо от исходного типа"""
        if isinstance(question_obj, QuestionServiceDTO):
            return question_obj

        if isinstance(question_obj, QuestionRepositoryDTO):
            return to_service_question(question_obj)

        if hasattr(question_obj, "id"):
            question_repo = QuestionRepositoryDTO.custom(question_obj)
            return to_service_question(question_repo)

        raise ValueError(f"Unsupported question object type: {type(question_obj)}")

    @staticmethod
    def _extract_subject_name(question_obj) -> str | None:
        """Попробовать получить название предмета из исходного объекта вопроса"""
        subject = getattr(question_obj, "subject", None)
        if subject and getattr(subject, "name", None):
            return subject.name

        if hasattr(question_obj, "question"):
            nested_subject = getattr(question_obj.question, "subject", None)
            if nested_subject and getattr(nested_subject, "name", None):
                return nested_subject.name

        return getattr(question_obj, "subject_name", None)

    @staticmethod
    def _extract_topic_name(question_obj) -> str | None:
        """Попробовать получить название темы из исходного объекта вопроса"""
        topic = getattr(question_obj, "topic", None)
        if topic and getattr(topic, "name", None):
            return topic.name

        if hasattr(question_obj, "question"):
            nested_topic = getattr(question_obj.question, "topic", None)
            if nested_topic and getattr(nested_topic, "name", None):
                return nested_topic.name

        return getattr(question_obj, "topic_name", None)

    def _invalidate_attempt_cache(
        self,
        student_guid: UUID,
        attempt_id: int | None = None,
        exam_type: ExamType | None = None,
    ):
        """Инвалидировать кеши попыток ЕНТ"""
        resources = [
            "ent_statistic",
            "ent_attempts_history",
        ]

        if attempt_id:
            resources.append("ent_attempt_detail")
            # Удалить конкретный детальный кеш
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="ent_attempt_detail",
                    user_id=student_guid,
                    params=f"attempt_id:{attempt_id}",
                )
            )

        # Инвалидировать с учетом типа экзамена
        if exam_type:
            exam_str = exam_type.value
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="ent_statistic",
                    user_id=student_guid,
                    params=f"exam_type:{exam_str}",
                )
            )

        # Инвалидировать все остальные кеши
        deleted = self._cache_service.invalidate_by_resources(
            resources, user_id=student_guid
        )
        logger.info(
            "Invalidated ENT attempt cache for user %s, deleted %s keys",
            student_guid,
            deleted,
        )
