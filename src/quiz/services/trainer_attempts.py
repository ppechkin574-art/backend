import logging

# from datetime import datetime
from typing import Protocol
from uuid import UUID

from quiz.converters import to_test_attempt_create
from quiz.dtos.enums import Status
from quiz.dtos.questions import QuestionWithAnswerServiceDTO

# from quiz.dtos.statistic import (
#     TopicAttemptDetailDTO,
#     TopicStatisticDailyDTO,
#     TopicStatisticGetServiceDTO,
#     TopicStatisticOverallDTO,
#     TopicStatisticServiceDTO,
# )
from quiz.dtos.trainer_attempt_answers import (
    TestAnswerServiceDTO,
    TrainerAttemptAnswerCreateRepositoryDTO,
    TrainerAttemptAnswerServiceDTO,
)
from quiz.dtos.trainer_attempts import (
    FinishAttemptResponseDTO,
    QuestionResultDTO,
    QuestionWithAnswerDetailDTO,
    TestCreateRepositoryDTO,
    TrainerAttemptAnswerResponseDTO,
    TrainerAttemptCreateServiceDTO,
    TrainerAttemptDetailDTO,
    TrainerAttemptRepositoryDTO,
    TrainerAttemptServiceDTO,
    VariantWithAnswerDTO,
)
from quiz.exceptions import (
    AttemptCompleted,
    AttemptNotCompleted,
    NoQuestionsInTrainerAttempt,
    TestQuestionNotExist,
    TrainerAttemptNotExist,
)
from quiz.services.cashback import CashbackService
from quiz.services.modules import ModuleLessonService
from quiz.uows.uows import UnitOfWorkTests
from quiz.utils.hint_transform import transform_video_hint
from quiz.utils.init import (
    AnswerCalculator,
    AttemptValidator,
    ProgressRecorder,
    QuestionPreparer,
    # StatisticsCalculator,
    # StreakCalculator,
    TimeNormalizerService,
    VariantValidator,
)
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class TrainerAttemptServiceInterface(Protocol):
    def create(self, test_attempt: TestCreateRepositoryDTO, locale: str = "ru") -> TrainerAttemptServiceDTO:
        raise NotImplementedError

    def answer(self, answer: TestAnswerServiceDTO) -> TrainerAttemptAnswerResponseDTO:
        raise NotImplementedError

    # def get_gt_id(self, id_: int, size: int) -> list[TrainerAttemptServiceDTO]:
    #     raise NotImplementedError

    # def get_topic_statistic(self, stat_params: TopicStatisticGetServiceDTO) -> TopicStatisticServiceDTO:
    #     raise NotImplementedError

    def finish_attempt(self, test_attempt_id: int, student_guid: UUID) -> FinishAttemptResponseDTO:
        raise NotImplementedError

    def get_trainers_by_subject(self, subject_id: int) -> list[dict]:
        raise NotImplementedError

    def get_attempt_result(self, attempt_id: int, student_guid: UUID) -> FinishAttemptResponseDTO:
        raise NotImplementedError


class TrainerAttemptService:
    def __init__(
        self,
        uow: UnitOfWorkTests,
        cache_service: CacheService,
        module_lesson_service: ModuleLessonService,
        cashback_service: CashbackService,
    ):
        self._uow = uow
        self._cache_service = cache_service
        self.module_lesson_service = module_lesson_service
        self._cashback_service = cashback_service
        self.max_time_per_question = 30 * 60

    def create(self, test: TrainerAttemptCreateServiceDTO, locale: str = "ru") -> TrainerAttemptServiceDTO:
        with self._uow:
            existing = self._uow.trainer_attempts.get_active_for_student(
                student_guid=test.student_guid, topic_id=test.topic_id
            )

            if existing:
                result = self._convert_to_service_dto(self._uow.trainer_attempts.get_with_questions(existing.id))
                if locale == "kk":
                    self._splice_kk_translations(result)
                return result

            test_attempt_repo = self._uow.trainer_attempts.create(
                to_test_attempt_create(test, self._uow.trainer_attempts.get_trainer_by_topic(test.topic_id))
            )
            self._uow.commit()

            questions = self._select_questions(test_attempt_repo)
            if questions:
                first_topic_id = questions[0].topic_id
                for _i, question in enumerate(questions):
                    if question.topic_id != first_topic_id:
                        self._uow.rollback()
                        raise ValueError(
                            f"Questions from different topics found: {first_topic_id} and {question.topic_id}"
                        )

            self._uow.commit()

            test_attempt_with_questions = self._uow.trainer_attempts.get_with_questions(test_attempt_repo.id)
            logger.info(
                "Trainer attempt %s created with %s questions",
                test_attempt_repo.id,
                len(test_attempt_with_questions.questions),
            )

            result = self._convert_to_service_dto(test_attempt_with_questions)
            if locale == "kk":
                self._splice_kk_translations(result)
            return result

    def answer(self, answer: TestAnswerServiceDTO) -> TrainerAttemptAnswerResponseDTO:
        with self._uow:
            try:
                test_attempt = self._uow.trainer_attempts.get_by_question_id(answer.trainer_attempt_question_id)
            except TrainerAttemptNotExist:
                raise TestQuestionNotExist(f"Question {answer.trainer_attempt_question_id} not found in any attempt")

            AttemptValidator.validate_attempt_exists(test_attempt, test_attempt.id, answer.student_guid)
            AttemptValidator.validate_attempt_not_completed(test_attempt)

            if answer.variants:
                question = self._get_question_for_answer(answer.trainer_attempt_question_id)

                valid_variant_ids = VariantValidator.get_valid_variant_ids(question)
                VariantValidator.validate_variants_belong_to_question(
                    question_id=question.id,
                    variant_ids=answer.variants,
                    valid_variant_ids=valid_variant_ids,
                )

                correct_variant_ids = {v.id for v in question.variants if v.is_correct}
                chosen_variant_ids = set(answer.variants)

                is_correct, _ = AnswerCalculator.calculate_correctness(
                    question_type=question.type.value,
                    chosen_variant_ids=chosen_variant_ids,
                    correct_variant_ids=correct_variant_ids,
                )
            else:
                question = None
                is_correct = False

            capped_spend_time = TimeNormalizerService.cap_question_time(answer.spend_time, self.max_time_per_question)

            self._uow.trainer_attempts.update_question_spend_time(answer.trainer_attempt_question_id, capped_spend_time)

            created_answers = []

            for _, variant in enumerate(answer.variants):
                if not variant:
                    raise ValueError("Variant is required")

                try:
                    answer_create = TrainerAttemptAnswerCreateRepositoryDTO(
                        trainer_attempt_question_id=answer.trainer_attempt_question_id,
                        variant_id=variant,
                        student_guid=answer.student_guid,
                    )

                    created_answers.append(self._uow.trainer_attempts.create_answer(answer_create))

                    self._uow.commit()

                except Exception as e:
                    logger.exception("Failed to save answer variant %s: %s", variant, e)
                    self._uow.rollback()
                    raise

            attempt_with_questions = self._uow.trainer_attempts.get_with_questions(test_attempt.id)
            total_questions = len(attempt_with_questions.questions) if attempt_with_questions.questions else 0

            answered_questions = sum(
                1 for q in (attempt_with_questions.questions or []) if q.answers and len(q.answers) > 0
            )

            is_completed = answered_questions == total_questions

            result = {
                "trainer_attempt_question_id": answer.trainer_attempt_question_id,
                "answered_variants": answer.variants,
                "is_correct": is_correct,
                "correct_variants": (list(correct_variant_ids) if answer.variants else []),
                "is_completed": is_completed,
                "total_questions": total_questions,
                "answered_questions": answered_questions,
                "attempt_id": test_attempt.id,
            }

            self._invalidate_trainer_attempt_cache(
                answer.student_guid,
                test_attempt.id,
                getattr(test_attempt, "topic_id", None),
            )

            return result

    def _select_questions(self, test: TrainerAttemptRepositoryDTO):
        with self._uow:
            questions = self._uow.trainer_attempts.get_questions_by_trainer(test.trainer_id)

            if not questions:
                raise NoQuestionsInTrainerAttempt

            for _, question in enumerate(questions):
                self._uow.trainer_attempts.add_question(test.id, question.id)

            return questions

    def finish_attempt(self, test_attempt_id: int, student_guid: UUID) -> FinishAttemptResponseDTO:
        with self._uow:
            attempt = self._uow.trainer_attempts.get_by_id(test_attempt_id)

            AttemptValidator.validate_attempt_exists(attempt, test_attempt_id, student_guid)

            if attempt and attempt.status == Status.completed:
                raise AttemptCompleted

            completed_attempt, _ = self._uow.trainer_attempts.finish_and_score(test_attempt_id)

            result = self._build_finish_attempt_response(completed_attempt)

            for question in completed_attempt.questions:
                question_obj = self._uow.questions.get_by_id(question.id)

                chosen_variant_ids = [a.variant_id for a in (question.answers or []) if a.variant_id]

                correct_variant_ids = [v.id for v in (question_obj.variants or []) if v.is_correct]

                is_correct = set(chosen_variant_ids) == set(correct_variant_ids)

                ProgressRecorder.record_attempt_progress(
                    uow=self._uow,
                    user_id=student_guid,
                    question_id=question.id,
                    is_correct=is_correct,
                    attempt_type="trainer",
                    attempt_id=test_attempt_id,
                )

            logger.info(
                "Trainer %s attempt completed: earned %s points by %s correct, %s incorrect and %s skipped answers. Average time per question: %s",
                test_attempt_id,
                result.score,
                result.correct_answers,
                result.incorrect_answers,
                result.skipped_answers,
                result.average_time_per_question,
            )

            attempt_trainer_id = attempt.trainer_id if hasattr(attempt, "trainer_id") else None

            self._uow.commit()

            try:
                self._invalidate_lesson_progress_cache(student_guid)

                self._update_lesson_progress_from_trainer_attempt(test_attempt_id, student_guid)

                self._invalidate_lesson_cache_for_trainer(attempt_trainer_id, student_guid)
            except Exception as e:
                logger.exception("Error updating lesson progress: %s", str(e))

            self._invalidate_trainer_attempt_cache(
                student_guid,
                test_attempt_id,
                attempt_trainer_id,
                attempt.topic_id if hasattr(attempt, "topic_id") else None,
            )

            # A completed trainer attempt counts toward streak. Bust
            # enhanced_global_statistic so Stats screen shows the new
            # streak immediately instead of waiting up to 1h TTL.
            self._cache_service.delete_pattern(
                f"user:{student_guid}:enhanced_global_statistic:*"
            )

            self._cashback_service.check_and_update(student_guid)

            return result

    # def _calculate_streak(self, student_guid: UUID) -> int:
    #     with self._uow:
    #         return StreakCalculator.calculate_streak(
    #             activity_dates=self._uow.trainer_attempts.get_completed_dates(
    #                 student_guid
    #             ),
    #             timezone_offset_hours=0,
    #             include_today=True,
    #         )

    def _get_question_for_answer(self, trainer_attempt_question_id: int):
        with self._uow:
            question = self._uow.trainer_attempts.get_question_by_attempt_question_id(trainer_attempt_question_id)

            if not question:
                raise TestQuestionNotExist(f"Question for attempt question {trainer_attempt_question_id} not found")

            return question

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="trainers_by_subject")
    def get_trainers_by_subject(self, subject_id: int) -> list[dict]:
        with self._uow:
            topics = self._uow.topics.get_by_subject_id(subject_id)

            result = []
            for topic in topics:
                trainers = self._uow.trainers.get_trainers_by_topic_id(topic.id)
                trainers_info = []
                for trainer in trainers:
                    try:
                        question_count = self._uow.questions.count_all(trainer.id)
                    except AttributeError:
                        question_count = self._uow.questions.count_by_topic(topic.id)

                    trainers_info.append(
                        {
                            "id": trainer.id,
                            "name": trainer.name,
                            "question_count": question_count,
                        }
                    )
                if trainers_info:
                    result.append(
                        {
                            "id": topic.id,
                            "name": topic.name,
                            "subject_id": topic.subject_id,
                            "trainers": trainers_info,
                        }
                    )

            return result

    @cached(
        strategy=CacheStrategy.USER,
        ttl=3600,
        resource="last_completed_attempt_statistics",
    )
    def get_last_completed_attempt_statistics(self, trainer_id: int, student_guid: UUID) -> TrainerAttemptDetailDTO:
        with self._uow:
            attempts = self._uow.trainer_attempts.get_user_trainer_attempts(str(student_guid), trainer_id)

            completed_attempts = [attempt for attempt in attempts if attempt.status == Status.completed]

            if not completed_attempts:
                raise TrainerAttemptNotExist(
                    f"No completed attempts found for trainer {trainer_id} and student {student_guid}"
                )

            attempt = completed_attempts[0]

            attempt_repo = self._uow.trainer_attempts.get_with_questions(attempt.id)

            stats = self._uow.trainer_attempts.get_attempt_statistic(attempt.id)

            trainer = self._uow.trainers.get_by_id(trainer_id)
            topic = None
            subject = None
            if trainer and trainer.topic_id:
                topic = self._uow.topics.get_by_id(trainer.topic_id)
                if topic and topic.subject_id:
                    subject = self._uow.subjects.get_by_id(topic.subject_id)

            questions_with_answers = []
            for idx, question_repo in enumerate(attempt_repo.questions or []):
                user_variant_ids = {
                    answer.variant_id for answer in (question_repo.answers or []) if answer.variant_id is not None
                }

                prepared_question = QuestionPreparer.prepare_question_with_answers(
                    question_obj=question_repo,
                    user_variant_ids=list(user_variant_ids),
                    question_number=idx + 1,
                )

                questions_with_answers.append(
                    QuestionWithAnswerDetailDTO(
                        id=prepared_question["id"],
                        guid=prepared_question["guid"],
                        topic_id=prepared_question["topic_id"],
                        subject_id=prepared_question["subject_id"],
                        difficulty=prepared_question["difficulty"],
                        type=prepared_question["type"],
                        blocks=prepared_question["blocks"],
                        hint=prepared_question["hint"],
                        variants=[
                            VariantWithAnswerDTO(
                                id=v["id"],
                                blocks=v["blocks"],
                                is_correct=v["is_correct"],
                                weight=v["weight"],
                                user_selected=v["user_selected"],
                            )
                            for v in prepared_question["variants"]
                        ],
                        question_number=prepared_question["question_number"],
                        is_correct=prepared_question["is_correct"],
                        topic_name=topic.name if topic else None,
                        task_description_ru=prepared_question.get("task_description_ru"),
                        task_description_kk=prepared_question.get("task_description_kk"),
                        question_translation_ru=prepared_question.get("question_translation_ru"),
                        question_translation_kk=prepared_question.get("question_translation_kk"),
                        explanation_ru=prepared_question.get("explanation_ru"),
                        explanation_kk=prepared_question.get("explanation_kk"),
                    )
                )

            total_answered = stats["correct"] + stats["incorrect"]
            accuracy = (stats["correct"] / total_answered * 100) if total_answered > 0 else 0.0

            spend_time = stats.get("spend_time", 0)
            if not spend_time and attempt.completed_at and attempt.started_at:
                spend_time = int((attempt.completed_at - attempt.started_at).total_seconds())

            return TrainerAttemptDetailDTO(
                id=attempt.id,
                accuracy=accuracy,
                status=attempt.status,
                score=stats["score"],
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
                total_questions=stats["total_questions"],
                correct_answers=stats["correct"],
                incorrect_answers=stats["incorrect"],
                skipped_answers=stats["skiped"],
                partial_correct_answers=0,
                spend_time_seconds=spend_time,
                trainer_id=trainer_id,
                trainer_name=trainer.name if trainer else None,
                topic_id=topic.id if topic else None,
                topic_name=topic.name if topic else None,
                subject_id=subject.id if subject else None,
                subject_name=subject.name if subject else None,
                questions=questions_with_answers,
            )

    def _splice_kk_translations(self, result: TrainerAttemptServiceDTO) -> None:
        """Replace question/variant blocks with KK text for Math questions.

        No-op when question_text_kk is NULL (non-Math subjects already store
        KK text in the original blocks — this only matters for Math where the
        source content is Russian).  Two batched SELECTs in a fresh UoW so
        this is safe to call after _select_questions (which closes its own
        nested session).  Same pattern as EntAttemptService._localize_questions_kk.
        """
        from sqlalchemy import bindparam, text

        from quiz.dtos.hint import localize_hint_blocks_with_kk_text
        from quiz.dtos.questions import localize_blocks_with_kk_text

        questions = result.questions or []
        if not questions:
            return

        question_ids = [q.id for q in questions if q.id is not None]
        if not question_ids:
            return

        with self._uow:
            q_stmt = text(
                "SELECT id, question_text_kk, hint_text_kk FROM questions WHERE id IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            q_kk: dict[int, tuple[str | None, str | None]] = {
                row[0]: (row[1], row[2])
                for row in self._uow.session.execute(q_stmt, {"ids": question_ids}).fetchall()
            }

            variant_ids = [v.id for q in questions for v in (q.variants or []) if v.id is not None]
            v_kk: dict[int, str] = {}
            if variant_ids:
                v_stmt = text(
                    "SELECT id, variant_text_kk FROM variants WHERE id IN :ids AND variant_text_kk IS NOT NULL"
                ).bindparams(bindparam("ids", expanding=True))
                for row in self._uow.session.execute(v_stmt, {"ids": variant_ids}).fetchall():
                    v_kk[row[0]] = row[1]

        for q in questions:
            if q.id is None:
                continue
            kk = q_kk.get(q.id)
            if not kk:
                continue
            q_text_kk, hint_text_kk = kk
            if q_text_kk:
                q.blocks = localize_blocks_with_kk_text(q.blocks, q_text_kk)
            if hint_text_kk and q.hint is not None and getattr(q.hint, "blocks", None):
                q.hint.blocks = localize_hint_blocks_with_kk_text(q.hint.blocks, hint_text_kk)
            for v in q.variants or []:
                if v.id is not None:
                    kk_str = v_kk.get(v.id)
                    if kk_str:
                        v.blocks = localize_blocks_with_kk_text(v.blocks, kk_str)

    def _convert_to_service_dto(self, repo_dto: TrainerAttemptRepositoryDTO) -> TrainerAttemptServiceDTO:
        service_questions = []
        for _i, question in enumerate(repo_dto.questions or []):
            service_answers = []
            for answer in question.answers or []:
                service_answer = TrainerAttemptAnswerServiceDTO(
                    id=answer.id,
                    trainer_attempt_question_id=answer.trainer_attempt_question_id,
                    variant_id=answer.variant_id,
                )
                service_answers.append(service_answer)

            transformed_hint = transform_video_hint(question.hint)

            service_question = QuestionWithAnswerServiceDTO(
                trainer_attempt_question_id=question.trainer_attempt_question_id,
                id=question.id,
                guid=question.guid,
                topic_id=question.topic_id,
                subject_id=question.subject_id,
                difficulty=question.difficulty,
                type=question.type,
                blocks=question.blocks,
                hint=transformed_hint,
                variants=question.variants,
                answers=service_answers,
                task_description_ru=getattr(question, "task_description_ru", None),
                task_description_kk=getattr(question, "task_description_kk", None),
                question_translation_ru=getattr(question, "question_translation_ru", None),
                question_translation_kk=getattr(question, "question_translation_kk", None),
                explanation_ru=getattr(question, "explanation_ru", None),
                explanation_kk=getattr(question, "explanation_kk", None),
            )
            service_questions.append(service_question)

        result = TrainerAttemptServiceDTO(
            id=repo_dto.id,
            student_guid=repo_dto.student_guid,
            trainer_id=repo_dto.trainer_id,
            status=repo_dto.status,
            started_at=repo_dto.started_at,
            completed_at=repo_dto.completed_at,
            questions=service_questions,
        )
        return result

    # @cached(strategy=CacheStrategy.USER, ttl=3600, resource="topic_statistic")
    # def get_topic_statistic(self, stat_params: TopicStatisticGetServiceDTO) -> TopicStatisticServiceDTO:
    #     start_dt = datetime.fromtimestamp(stat_params.ts_start)
    #     end_dt = datetime.fromtimestamp(stat_params.ts_end)
    #     with self._uow:
    #         attempts = self._uow.trainer_attempts.get_completed_attempts_by_period(
    #             student_guid=stat_params.student_guid,
    #             topic_id=stat_params.topic_id,
    #             start_date=start_dt,
    #             end_date=end_dt,
    #         )

    #         if not attempts:
    #             logger.info("No completed attempts found for the given period")
    #             empty_overall = TopicStatisticOverallDTO(
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
    #             return TopicStatisticServiceDTO(
    #                 overall=empty_overall,
    #                 daily=[],
    #                 streak=0,
    #                 attempts=[],
    #             )

    #         statistics = StatisticsCalculator.calculate_attempts_statistics(
    #             attempts=attempts,
    #             get_attempt_stats_func=lambda attempt_id: self._uow.trainer_attempts.get_attempt_statistic(attempt_id),
    #             get_question_times_func=self._get_question_times_for_attempt,
    #             exam_type="trainer",
    #             timezone_offset_hours=0,
    #         )

    #         overall_data = StatisticsCalculator.calculate_overall_statistics(statistics, include_partial=True)

    #         daily_data = StatisticsCalculator.calculate_daily_statistics(
    #             statistics["daily_stats"], include_partial=True
    #         )

    #         streak = self._calculate_streak(stat_params.student_guid)

    #         attempts_details = []
    #         for attempt_stat in statistics["all_attempt_stats"]:
    #             attempt = next((a for a in attempts if a.id == attempt_stat["attempt_id"]), None)
    #             trainer_name = getattr(attempt.trainer, "name", "Unknown") if attempt else "Unknown"

    #             attempts_details.append(
    #                 TopicAttemptDetailDTO(
    #                     attempt_id=attempt_stat["attempt_id"],
    #                     trainer_name=trainer_name,
    #                     completed_at=attempt_stat["completed_at"],
    #                     correct_answers=attempt_stat["correct_answers"],
    #                     total_questions=attempt_stat["total_questions"],
    #                     spend_time=attempt_stat["spend_time"],
    #                     score=attempt_stat["score"],
    #                     time_correction_applied=attempt_stat["time_correction_applied"],
    #                 )
    #             )

    #         overall_stats = TopicStatisticOverallDTO(
    #             total_attempts=overall_data["total_attempts"],
    #             total_correct_answers=overall_data["total_correct_answers"],
    #             total_partial_correct_answers=overall_data.get("total_partial_correct_answers", 0),
    #             total_questions=overall_data["total_questions"],
    #             total_spend_time=overall_data["total_spend_time"],
    #             avg_correct_percentage=overall_data["avg_correct_percentage"],
    #             overall_avg_time_per_question=overall_data["overall_avg_time_per_question"],
    #             median_time_per_question=overall_data["median_time_per_question"],
    #             avg_score=overall_data["avg_score"],
    #             avg_spend_time=overall_data["avg_spend_time"],
    #         )

    #         daily_stats = [
    #             TopicStatisticDailyDTO(
    #                 date=daily["date"],
    #                 total_attempts=daily["total_attempts"],
    #                 total_correct_answers=daily["total_correct_answers"],
    #                 total_partial_correct_answers=daily.get("total_partial_correct_answers", 0),
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

    #         return TopicStatisticServiceDTO(
    #             overall=overall_stats,
    #             daily=daily_stats,
    #             streak=streak,
    #             attempts=attempts_details,
    #         )

    # def _get_question_times_for_attempt(self, attempt_id: int) -> list[int]:
    #     with self._uow:
    #         return [
    #             q.spend_time or 0
    #             for q in self._uow.trainer_attempts.get_questions_with_times(attempt_id)
    #             if q.spend_time
    #         ]

    def _invalidate_trainer_attempt_cache(
        self,
        student_guid: UUID,
        attempt_id: int | None = None,
        trainer_id: int | None = None,
        topic_id: int | None = None,
    ):
        resources = [
            "topic_statistic",
            "last_completed_attempt_statistics",
        ]

        if attempt_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="attempt_result",
                    user_id=student_guid,
                    params=f"attempt_id={attempt_id}",
                )
            )
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="attempt_details",
                    user_id=student_guid,
                    params=f"attempt_id={attempt_id}",
                )
            )

        if trainer_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="last_completed_attempt_statistics",
                    user_id=student_guid,
                    params=f"trainer_id={trainer_id}",
                )
            )

        if topic_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="topic_statistic",
                    user_id=student_guid,
                    params=f"topic_id:{topic_id}",
                )
            )

        deleted = self._cache_service.invalidate_by_resources(resources, user_id=student_guid)
        logger.info(
            "Invalidated trainer attempt cache for user %s, deleted %s keys",
            student_guid,
            deleted,
        )

    def _update_lesson_progress_from_trainer_attempt(self, attempt_id: int, student_guid: UUID) -> None:
        with self._uow:
            attempt_with_questions = self._uow.trainer_attempts.get_with_questions(attempt_id)
            if not attempt_with_questions:
                logger.warning("Attempt %s not found", attempt_id)
                return
            if attempt_with_questions.status != Status.completed:
                raise AttemptNotCompleted(f"Attempt {attempt_id} is not completed")

            trainer = self._uow.trainers.get_by_id(attempt_with_questions.trainer_id)
            if not trainer:
                raise TrainerAttemptNotExist(f"Trainer {attempt_with_questions.trainer_id} not found")
            if not trainer.topic_id:
                logger.warning("Trainer %s has no topic_id", attempt_with_questions.trainer_id)
                return

            topic_id = trainer.topic_id
            lessons = self._uow.module_lessons.get_by_topic(topic_id)
            if not lessons:
                logger.info("No lessons found for topic %s, stopping.", topic_id)
                return

            attempt_statistics = self._uow.trainer_attempts.get_attempt_statistic(attempt_id)
            if not attempt_statistics:
                logger.warning("Could not get statistics for attempt %s", attempt_id)
                return

            total_questions = attempt_statistics.get("total_questions", 0)
            correct_answers = attempt_statistics.get("correct", 0)
            spend_time_seconds = attempt_statistics.get("spend_time", 0)

            logger.info(
                "Attempt stats: %s total_questions with %s correct_answers by %ss",
                total_questions,
                correct_answers,
                spend_time_seconds,
            )

            updated_lesson_ids = []
            updated_module_ids = set()

            for lesson in lessons:
                try:
                    updated_progress = self.module_lesson_service.update_lesson_progress(
                        lesson_id=lesson.id,
                        user_id=student_guid,
                        completed_test=True,
                        test_score=correct_answers,
                        test_max_score=total_questions,
                        time_spent=spend_time_seconds,
                    )
                    updated_lesson_ids.append(lesson.id)
                    updated_module_ids.add(lesson.module_id)
                    logger.info(
                        "Updated lesson %s progress: %s completed test with %s/%s test_score, isCompleted=%s",
                        lesson.id,
                        updated_progress.completed_test,
                        updated_progress.test_score,
                        updated_progress.test_max_score,
                        updated_progress.is_completed,
                    )

                    self._cache_service.delete(
                        self._cache_service.make_key(
                            CacheStrategy.GLOBAL,
                            resource="lesson_with_details",
                            params=f"id:{lesson.id},user_id:{student_guid}",
                        )
                    )
                    self._cache_service.delete(
                        self._cache_service.make_key(
                            CacheStrategy.USER,
                            resource="lesson_progress",
                            user_id=str(student_guid),
                            params=f"lesson_id:{lesson.id}",
                        )
                    )
                except Exception as e:
                    logger.exception("Error updating progress for lesson %s: %s", lesson.id, e)
                    continue

            self._uow.commit()

            for lesson_id in updated_lesson_ids:
                self._cache_service.delete(
                    self._cache_service.make_key(
                        CacheStrategy.GLOBAL,
                        resource="lesson_with_details",
                        params=f"id:{lesson_id},user_id:{student_guid}",
                    )
                )
                self._cache_service.delete(
                    self._cache_service.make_key(
                        CacheStrategy.USER,
                        resource="lesson_progress",
                        user_id=str(student_guid),
                        params=f"lesson_id:{lesson_id}",
                    )
                )
                logger.info("Invalidated cache for %s lesson", lesson_id)

            for module_id in updated_module_ids:
                self._cache_service.delete(
                    self._cache_service.make_key(
                        CacheStrategy.GLOBAL,
                        resource="lessons_by_module",
                        params=f"module_id:{module_id}:page=1:page_size=20:search=None:sort_by=None:sort_order=asc",
                    )
                )
                logger.info("Invalidated cache for %s module", module_id)

    def _invalidate_lesson_progress_cache(self, student_guid: UUID):
        resources = ["lesson_progress", "lessons_by_module", "modules_by_subject"]

        deleted = self._cache_service.invalidate_by_resources(resources, user_id=str(student_guid))
        logger.info(
            "Invalidated lesson progress cache for %s user, deleted %s keys",
            student_guid,
            deleted,
        )

    def _invalidate_lesson_cache_for_trainer(self, trainer_id: int, student_guid: UUID):
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer or not trainer.topic_id:
                return
            lessons = self._uow.module_lessons.get_by_topic(trainer.topic_id)
            for lesson in lessons:
                self._cache_service.delete(
                    self._cache_service.make_key(
                        CacheStrategy.GLOBAL,
                        resource="lesson_with_details",
                        params=f"lesson_id={lesson.id}:user_id={student_guid}",
                    )
                )
            logger.info(
                "Invalidated lesson cache for %s trainer, %s user",
                trainer_id,
                student_guid,
            )

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="attempt_result")
    def get_attempt_result(self, attempt_id: int, student_guid: UUID) -> FinishAttemptResponseDTO:
        with self._uow:
            attempt = self._uow.trainer_attempts.get_with_questions(attempt_id)
            if not attempt:
                raise TrainerAttemptNotExist(f"Attempt {attempt_id} not found")
            if attempt.student_guid != student_guid:
                raise PermissionError("You don't have access to this attempt")
            if attempt.status != Status.completed:
                raise AttemptNotCompleted(f"Attempt {attempt_id} is not completed")
            return self._build_finish_attempt_response(attempt)

    def _build_finish_attempt_response(self, attempt: TrainerAttemptRepositoryDTO) -> FinishAttemptResponseDTO:
        total_questions = len(attempt.questions) if attempt.questions else 0
        correct_answers = 0
        incorrect_answers = 0
        skipped_answers = 0
        total_spend_time = 0.0
        question_results = []
        correct_question_ids = []
        incorrect_question_ids = []

        for question in attempt.questions:
            chosen_variant_ids = [a.variant_id for a in (question.answers or []) if a.variant_id is not None]

            correct_variant_ids = [v.id for v in (question.variants or []) if v.is_correct]

            is_correct = set(chosen_variant_ids) == set(correct_variant_ids)

            spend_time = getattr(question, "spend_time", 0) or 0
            total_spend_time += spend_time

            question_text = ""
            if question.blocks and len(question.blocks) > 0:
                first_block = question.blocks[0]
                if hasattr(first_block, "value"):
                    question_text = first_block.value
                elif hasattr(first_block, "text"):
                    question_text = first_block.text

            question_result = QuestionResultDTO(
                question_id=question.id,
                is_correct=is_correct,
                chosen_variant_ids=chosen_variant_ids,
                correct_variant_ids=correct_variant_ids,
                spend_time=spend_time,
                question_text=question_text,
                question_type=question.type,
            )
            question_results.append(question_result)

            if is_correct:
                correct_answers += 1
                correct_question_ids.append(question.id)
            else:
                if chosen_variant_ids:
                    incorrect_answers += 1
                    incorrect_question_ids.append(question.id)
                else:
                    skipped_answers += 1

        score = attempt.score if attempt.score else correct_answers
        max_score = total_questions
        average_time_per_question = total_spend_time / total_questions if total_questions > 0 else 0

        return FinishAttemptResponseDTO(
            attempt_id=attempt.id,
            status=attempt.status,
            score=score,
            correct_answers=correct_answers,
            incorrect_answers=incorrect_answers,
            max_score=max_score,
            completed_at=attempt.completed_at,
            question_results=question_results,
            correct_question_ids=correct_question_ids,
            incorrect_question_ids=incorrect_question_ids,
            total_questions=total_questions,
            skipped_answers=skipped_answers,
            total_spend_time=total_spend_time,
            average_time_per_question=average_time_per_question,
            trainer_id=attempt.trainer_id,
            started_at=attempt.started_at,
        )

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="attempt_details")
    def get_attempt_details(self, attempt_id: int, student_guid: UUID) -> TrainerAttemptDetailDTO:
        with self._uow:
            attempt = self._uow.trainer_attempts.get_by_id(attempt_id)
            if not attempt:
                raise TrainerAttemptNotExist(f"Attempt {attempt_id} not found")
            if attempt.student_guid != student_guid:
                raise PermissionError("You don't have access to this attempt")
            if attempt.status != Status.completed:
                raise AttemptNotCompleted(f"Attempt {attempt_id} is not completed")

            attempt_repo = self._uow.trainer_attempts.get_with_questions(attempt_id)
            stats = self._uow.trainer_attempts.get_attempt_statistic(attempt_id)

            trainer = self._uow.trainers.get_by_id(attempt_repo.trainer_id)
            topic = self._uow.topics.get_by_id(trainer.topic_id) if trainer and trainer.topic_id else None
            subject = self._uow.subjects.get_by_id(topic.subject_id) if topic and topic.subject_id else None

            questions_with_answers = []
            for idx, question_repo in enumerate(attempt_repo.questions or []):
                user_variant_ids = {answer.variant_id for answer in (question_repo.answers or []) if answer.variant_id}
                prepared_question = QuestionPreparer.prepare_question_with_answers(
                    question_obj=question_repo,
                    user_variant_ids=list(user_variant_ids),
                    question_number=idx + 1,
                )
                questions_with_answers.append(
                    QuestionWithAnswerDetailDTO(
                        id=prepared_question["id"],
                        guid=prepared_question["guid"],
                        topic_id=prepared_question["topic_id"],
                        subject_id=prepared_question["subject_id"],
                        difficulty=prepared_question["difficulty"],
                        type=prepared_question["type"],
                        blocks=prepared_question["blocks"],
                        hint=prepared_question["hint"],
                        variants=[
                            VariantWithAnswerDTO(
                                id=v["id"],
                                blocks=v["blocks"],
                                is_correct=v["is_correct"],
                                weight=v["weight"],
                                user_selected=v["user_selected"],
                            )
                            for v in prepared_question["variants"]
                        ],
                        question_number=prepared_question["question_number"],
                        is_correct=prepared_question["is_correct"],
                        topic_name=topic.name if topic else None,
                        task_description_ru=prepared_question.get("task_description_ru"),
                        task_description_kk=prepared_question.get("task_description_kk"),
                        question_translation_ru=prepared_question.get("question_translation_ru"),
                        question_translation_kk=prepared_question.get("question_translation_kk"),
                        explanation_ru=prepared_question.get("explanation_ru"),
                        explanation_kk=prepared_question.get("explanation_kk"),
                    )
                )

            total_answered = stats["correct"] + stats["incorrect"]
            spend_time = stats.get("spend_time", 0)

            if not spend_time and attempt_repo.completed_at and attempt_repo.started_at:
                spend_time = int((attempt_repo.completed_at - attempt_repo.started_at).total_seconds())

            return TrainerAttemptDetailDTO(
                id=attempt_repo.id,
                accuracy=((stats["correct"] / total_answered * 100) if total_answered > 0 else 0.0),
                status=attempt_repo.status,
                score=stats["score"],
                started_at=attempt_repo.started_at,
                completed_at=attempt_repo.completed_at,
                total_questions=stats["total_questions"],
                correct_answers=stats["correct"],
                incorrect_answers=stats["incorrect"],
                skipped_answers=stats["skiped"],
                partial_correct_answers=0,
                spend_time_seconds=spend_time,
                trainer_id=trainer.id if trainer else None,
                trainer_name=trainer.name if trainer else None,
                topic_id=topic.id if topic else None,
                topic_name=topic.name if topic else None,
                subject_id=subject.id if subject else None,
                subject_name=subject.name if subject else None,
                questions=questions_with_answers,
            )
