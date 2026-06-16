import logging
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import and_, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import case, func, literal_column, select

# from quiz.converters import to_ent_statistic_service_dto
from quiz.dtos.ent_answers import EntAttemptAnswerCreateRepositoryDTO
from quiz.dtos.ent_attempts import (
    # AdminAttemptFilterDTO,
    # AdminListQueryDTO,
    EntAttemptCreateRepositoryDTO,
    EntAttemptRepositoryDTO,
    EntAttemptStatisticRepositoryDTO,
)
from quiz.dtos.enums import ExamType, Status

# from quiz.dtos.statistic import (
#     EntStatisticDailyRepositoryDTO,
#     EntStatisticGetRepositoryDTO,
#     EntStatisticRepositoryDTO,
#     # EntStatisticServiceDTO,
# )
from quiz.exceptions import EntOptionsDoesntExist, TrainerAttemptNotExist
from quiz.models.edu_content import Question, Subject, Variant
from quiz.models.ent import EntAttempt, EntAttemptAnswer, EntOption, EntOptionQuestion
from quiz.utils.init import RepositoryHelpers

logger = logging.getLogger(__name__)


class EntAttemptRepositoryInterface(Protocol):
    def create(self, ent_attempt: EntAttemptCreateRepositoryDTO) -> EntAttemptRepositoryDTO:
        """Создание попытки решения варианта пробного ЕНТ"""
        raise NotImplementedError

    def answer(self, ent_answer: EntAttemptAnswerCreateRepositoryDTO) -> None:
        """Запись ответов пробного ЕНТ"""
        raise NotImplementedError

    # def get_answers(self, option_id: int):
    #     """Получение ответов для варианта пробного ЕНТ"""
    #     raise NotImplementedError

    # def get_statistic_by_student(
    #     self, ent_stat_params_dto: EntStatisticGetRepositoryDTO
    # ) -> EntStatisticRepositoryDTO:
    #     """Получение статистики прохождения пробного ЕНТ для студента"""
    #     raise NotImplementedError

    def get_active_for_student(self, student_guid: UUID, ent_option_id: int) -> EntAttemptRepositoryDTO | None:
        """Получить активную попытку ЕНТ"""
        raise NotImplementedError

    def get_attempt_by_id(self, attempt_id) -> EntAttempt:
        """Получить попытку ЕНТ по id"""
        raise NotImplementedError

    def get_attempt_statistic(
        self, ent_attempt_id: int, spend_time: int | None = None
    ) -> EntAttemptStatisticRepositoryDTO:
        raise NotImplementedError

    # def save_updates(self):
    #     raise NotImplementedError

    def save_attempt_updates(self, attempt: EntAttemptRepositoryDTO):
        """Сохраняет изменения конкретной попытки"""
        raise NotImplementedError

    def get_completed_attempts_by_period(
        self,
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType = None,
    ) -> list[EntAttempt]:
        """Сохраняет изменения конкретной попытки"""
        raise NotImplementedError


class EntAttemptRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, ent_attempt: EntAttemptCreateRepositoryDTO) -> EntAttemptRepositoryDTO:
        if (
            ent_attempt.exam_type
            and ent_attempt.exam_type.value == "by_subject"
            and not self._check_ent_option(ent_option_id=ent_attempt.ent_option_id)
        ):
            raise EntOptionsDoesntExist

        if ent_attempt.started_at and ent_attempt.started_at.tzinfo:
            ent_attempt.started_at = ent_attempt.started_at.astimezone(UTC)

        raw = ent_attempt.model_dump()
        allowed = {
            "student_guid",
            "ent_option_id",
            "status",
            "started_at",
            "deadline_at",
            "score",
            "current_question_index",
            "exam_type",
            "subject_combination_id",
            "full_exam_question_ids",
        }
        filtered = {k: v for k, v in raw.items() if k in allowed and v is not None}
        if "score" not in filtered:
            filtered["score"] = 0
        if "current_question_index" not in filtered:
            filtered["current_question_index"] = 0
        attempt = EntAttempt(**filtered)
        self._session.add(attempt)
        self._session.flush()
        self._session.refresh(attempt)
        logger.debug(
            "Created ENT attempt in DB: id=%s, student=%s",
            attempt.id,
            attempt.student_guid,
        )
        return EntAttemptRepositoryDTO.model_validate(attempt)

    def answer(self, ent_answer: EntAttemptAnswerCreateRepositoryDTO) -> None:
        qa = EntAttemptAnswer(**ent_answer.model_dump())
        self._session.add(qa)
        self._session.flush()

    def get_completed_dates(self, student_guid: UUID) -> set[date]:
        """Получает все даты, когда пользователь завершал ЕНТ попытки"""
        return RepositoryHelpers.get_completed_dates(
            session=self._session,
            model_class=EntAttempt,
            student_guid=student_guid,
        )

    def get_active_for_student(self, student_guid: UUID, ent_option_id: int) -> EntAttemptRepositoryDTO | None:
        result = (
            self._session.execute(
                select(EntAttempt).where(
                    EntAttempt.status == Status.in_progress,
                    EntAttempt.student_guid == student_guid,
                    EntAttempt.ent_option_id == ent_option_id,
                )
            )
            .scalars()
            .one_or_none()
        )
        if result:
            return EntAttemptRepositoryDTO.model_validate(result)
        return result

    def get_active_full_exam_for_student(
        self, student_guid: UUID, subject_combination_id: int
    ) -> EntAttemptRepositoryDTO | None:
        """Получить активную попытку полноценного экзамена"""
        result = (
            self._session.execute(
                select(EntAttempt).where(
                    EntAttempt.status == Status.in_progress,
                    EntAttempt.student_guid == student_guid,
                    EntAttempt.exam_type == ExamType.full_exam,
                    EntAttempt.subject_combination_id == subject_combination_id,
                )
            )
            .scalars()
            .one_or_none()
        )
        if result:
            return EntAttemptRepositoryDTO.model_validate(result)
        return result

    # def get_statistic_by_student(
    #     self, ent_stat_params_dto: EntStatisticGetRepositoryDTO
    # ) -> EntStatisticServiceDTO:
    #     overall_stats = self._get_statistic_by_student_overall(ent_stat_params_dto)

    #     daily_stats = self.get_daily_statistic_by_student(ent_stat_params_dto)

    #     return to_ent_statistic_service_dto(overall_stats, daily_stats)

    # def _get_statistic_by_student_overall(
    #     self, ent_stat_params_dto: EntStatisticGetRepositoryDTO
    # ) -> EntStatisticRepositoryDTO:
    #     q = self._session.execute(
    #         select(
    #             func.coalesce(func.count(EntAttempt.id), 0).label("tries"),
    #             func.coalesce(func.avg(EntAttempt.score), 0.0).label("avg_score"),
    #             func.coalesce(
    #                 func.avg(
    #                     func.extract(
    #                         "epoch", EntAttempt.completed_at - EntAttempt.started_at
    #                     )
    #                 ),
    #                 0.0,
    #             ).label("avg_spend_time"),
    #         )
    #         .select_from(EntAttempt)
    #         .where(
    #             EntAttempt.student_guid == ent_stat_params_dto.student_guid,
    #             EntAttempt.started_at
    #             >= func.to_timestamp(ent_stat_params_dto.ts_start),
    #             EntAttempt.started_at <= func.to_timestamp(ent_stat_params_dto.ts_end),
    #             EntAttempt.status == "completed",
    #         )
    #     ).first()
    #     return EntStatisticRepositoryDTO.model_validate(q._mapping)

    def get_attempt_by_id(self, attempt_id: int):
        obj = self._session.get(EntAttempt, attempt_id)
        if obj:
            return EntAttemptRepositoryDTO.model_validate(obj)
        return obj

    def _check_ent_option(self, ent_option_id):
        option = self._session.get(EntOption, ent_option_id)
        return bool(option)

    # def save_updates(self):
    #     self._session.flush()

    def save_attempt_updates(self, attempt: EntAttemptRepositoryDTO):
        db_attempt = self._session.get(EntAttempt, attempt.id)
        if db_attempt:
            db_attempt.status = attempt.status
            db_attempt.score = attempt.score
            db_attempt.completed_at = attempt.completed_at
            db_attempt.current_question_index = attempt.current_question_index
            self._session.flush()

    def award_points_once(self, attempt_id: int) -> bool:
        """Атомарно помечает попытку как «баллы уже начислены».

        Возвращает True ровно один раз — у победителя гонки.
        Все последующие вызовы (конкурентные или повторные) получают False.
        Использует PostgreSQL-атомарный UPDATE WHERE points_awarded = FALSE,
        что исключает двойное начисление без явной блокировки строки.
        """
        result = self._session.execute(
            text(
                "UPDATE ent_attempts "
                "SET points_awarded = TRUE "
                "WHERE id = :attempt_id AND points_awarded = FALSE "
                "RETURNING id"
            ),
            {"attempt_id": attempt_id},
        )
        return result.fetchone() is not None

    def update_full_exam_question_ids(self, attempt_id: int, questions_csv: str) -> None:
        attempt = self._session.get(EntAttempt, attempt_id)
        if attempt:
            attempt.full_exam_question_ids = questions_csv
            self._session.flush()

    def get_attempt_statistic(self, ent_attempt_id: int, spend_time: int | None) -> EntAttemptStatisticRepositoryDTO:
        ent_attempt = self._session.get(EntAttempt, ent_attempt_id)
        if not ent_attempt:
            raise TrainerAttemptNotExist(f"ENT attempt {ent_attempt_id} not found")

        if spend_time is None:
            if ent_attempt.completed_at and ent_attempt.started_at:
                started_at = ent_attempt.started_at
                completed_at = ent_attempt.completed_at

                started_at = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at.astimezone(UTC)

                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=UTC)
                else:
                    completed_at = completed_at.astimezone(UTC)

                spend_time = max(1, (completed_at - started_at).total_seconds())
                logger.info(
                    "Calculated spend time for attempt %s: %ss",
                    ent_attempt_id,
                    spend_time,
                )
            else:
                spend_time = 0
        elif spend_time < 0:
            logger.warning(
                "Negative spend time received for attempt %s: %s. Setting to 1.",
                ent_attempt_id,
                spend_time,
            )
            spend_time = 1

        if ent_attempt.exam_type == ExamType.full_exam:
            if ent_attempt.full_exam_question_ids:
                question_ids = [qid.strip() for qid in ent_attempt.full_exam_question_ids.split(",") if qid.strip()]
                total_questions = len(question_ids)
                logger.info(
                    "Full exam %s: %s questions from full_exam_question_ids",
                    ent_attempt_id,
                    total_questions,
                )
            else:
                total_questions = 0
                logger.warning("Full exam %s has empty full_exam_question_ids", ent_attempt_id)
        else:
            total_questions_query = (
                select(func.count(EntOptionQuestion.id))
                .select_from(EntAttempt)
                .join(EntOption, EntOption.id == EntAttempt.ent_option_id)
                .join(EntOptionQuestion, EntOptionQuestion.ent_option_id == EntOption.id)
                .where(EntAttempt.id == ent_attempt_id)
            )
            total_questions = self._session.scalar(total_questions_query) or 0

        # Rules of assessment:
        # - If user chose even one correct answer → correct
        # - If user chose not correct answer → incorrect
        # - If no variants provided → skipped (handled separately)
        #
        # Note: We filter out skipped questions (variant_id IS NULL) from this query
        # because they are counted separately. We also need to handle the case where
        # multiple variants are selected for the same question - we group by question_id
        # to count each question only once.
        answered_stats_query = (
            select(
                EntAttemptAnswer.ent_attempt_id,
                Variant.question_id,
                # Check if user selected at least one correct variant
                func.max(case((Variant.is_correct, 1), else_=0)).label("has_correct"),
                case(
                    # If user selected at least one correct variant → correct
                    # (even if they also selected incorrect ones)
                    (
                        func.max(case((Variant.is_correct, 1), else_=0)) == 1,
                        literal_column("'correct'"),
                    ),
                    # Otherwise, if user selected any variant (but none correct) → incorrect
                    else_=literal_column("'incorrect'"),
                ).label("result"),
            )
            .select_from(EntAttemptAnswer)
            .join(Variant, Variant.id == EntAttemptAnswer.variant_id)  # Use inner join to exclude NULL variants
            .where(
                and_(
                    EntAttemptAnswer.ent_attempt_id == ent_attempt_id,
                    EntAttemptAnswer.variant_id.isnot(None),  # Exclude skipped questions
                    Variant.question_id.isnot(None),  # Safety check
                )
            )
            .group_by(EntAttemptAnswer.ent_attempt_id, Variant.question_id)
            .cte("answered_stats")
        )

        answered_result = self._session.execute(
            select(
                # Count correct questions for score (1 point per correct question)
                func.count().filter(answered_stats_query.c.result == "correct").label("score"),
                func.count().filter(answered_stats_query.c.result == "correct").label("correct"),
                func.count().filter(answered_stats_query.c.result == "partial_correct").label("partial_correct"),
                func.count().filter(answered_stats_query.c.result == "incorrect").label("incorrect"),
            ).group_by(answered_stats_query.c.ent_attempt_id)
        ).first()

        skipped_count_query = select(func.count(EntAttemptAnswer.id)).where(
            EntAttemptAnswer.ent_attempt_id == ent_attempt_id,
            EntAttemptAnswer.variant_id.is_(None),
        )
        skipped_count = self._session.scalar(skipped_count_query) or 0

        # Check for potential data integrity issues:
        # Questions that have both variant answers AND skipped answers
        # This should not happen, but if it does, we need to handle it
        total_answer_records_query = select(func.count(EntAttemptAnswer.id)).where(
            EntAttemptAnswer.ent_attempt_id == ent_attempt_id
        )
        total_answer_records = self._session.scalar(total_answer_records_query) or 0

        # Count distinct questions that have variant answers
        distinct_answered_questions_query = (
            select(func.count(func.distinct(Variant.question_id)))
            .select_from(EntAttemptAnswer)
            .join(Variant, Variant.id == EntAttemptAnswer.variant_id)
            .where(
                and_(
                    EntAttemptAnswer.ent_attempt_id == ent_attempt_id,
                    EntAttemptAnswer.variant_id.isnot(None),
                    Variant.question_id.isnot(None),
                )
            )
        )
        distinct_answered_questions = self._session.scalar(distinct_answered_questions_query) or 0

        if not answered_result:
            score = 0
            correct = 0
            partial_correct = 0
            incorrect = 0
        else:
            score = int(answered_result.score) if answered_result.score else 0
            correct = answered_result.correct if answered_result.correct else 0
            partial_correct = answered_result.partial_correct if answered_result.partial_correct else 0
            incorrect = answered_result.incorrect if answered_result.incorrect else 0

        total_recorded_answers = correct + partial_correct + incorrect + skipped_count

        # Log detailed information for debugging
        logger.info(
            "ENT attempt %s detailed stats: total_answer_records=%s, distinct_answered_questions=%s, "
            "correct=%s, incorrect=%s, skipped=%s, total_questions=%s",
            ent_attempt_id,
            total_answer_records,
            distinct_answered_questions,
            correct,
            incorrect,
            skipped_count,
            total_questions,
        )

        if total_recorded_answers != total_questions:
            logger.warning(
                "Answer count mismatch for attempt %s: recorded=%s, expected=%s, total_questions=%s, "
                "total_answer_records=%s, distinct_answered_questions=%s",
                ent_attempt_id,
                total_recorded_answers,
                total_questions,
                total_questions,
                total_answer_records,
                distinct_answered_questions,
            )

            # If we have more answer records than questions, there might be duplicates
            if total_answer_records > total_questions:
                logger.warning(
                    "Possible duplicate answer records detected for attempt %s: "
                    "total_answer_records=%s > total_questions=%s",
                    ent_attempt_id,
                    total_answer_records,
                    total_questions,
                )

        logger.info(
            "ENT attempt %s statistics: score=%s, correct=%s, partial_correct=%s, incorrect=%s, skipped=%s, total_questions=%s, spend_time=%s",
            ent_attempt_id,
            score,
            correct,
            partial_correct,
            incorrect,
            skipped_count,
            total_questions,
            spend_time,
        )

        return EntAttemptStatisticRepositoryDTO(
            ent_attempt_id=ent_attempt_id,
            score=score,
            total_questions=total_questions,
            correct=correct,
            partial_correct=partial_correct,
            incorrect=incorrect,
            skiped=skipped_count,
            spend_time=int(spend_time) if spend_time is not None else 0,
        )

    # def list_admin_attempts(
    #     self, query: AdminListQueryDTO, filters: AdminAttemptFilterDTO
    # ) -> tuple[list[EntAttemptRepositoryDTO], int]:
    #     stmt = select(EntAttempt).options(
    #         joinedload(EntAttempt.options).joinedload(EntOption.subject)
    #     )

    #     conditions = []
    #     if filters.user_id:
    #         conditions.append(EntAttempt.student_guid == filters.user_id)
    #     if filters.status:
    #         conditions.append(EntAttempt.status == filters.status)
    #     if filters.date_from:
    #         conditions.append(EntAttempt.started_at >= filters.date_from)
    #     if filters.date_to:
    #         conditions.append(EntAttempt.started_at <= filters.date_to)

    #     if conditions:
    #         stmt = stmt.where(and_(*conditions))

    #     total_count = self._session.scalar(
    #         select(func.count()).select_from(stmt.subquery())
    #     )

    #     if query.sort_by:
    #         sort_column = getattr(EntAttempt, query.sort_by, None)
    #         if sort_column:
    #             if query.sort_order == "desc":
    #                 sort_column = sort_column.desc()
    #             stmt = stmt.order_by(sort_column)
    #     else:
    #         stmt = stmt.order_by(EntAttempt.started_at.desc())

    #     stmt = stmt.offset((query.page - 1) * query.page_size).limit(query.page_size)

    #     attempts = self._session.execute(stmt).scalars().all()
    #     return [
    #         EntAttemptRepositoryDTO.model_validate(attempt) for attempt in attempts
    #     ], total_count

    # def get_admin_platform_stats(self) -> dict:
    #     """Get platform-wide statistics for admin dashboard"""
    #     stats = self._session.execute(
    #         select(
    #             func.count(EntAttempt.id).label("total_attempts"),
    #             func.count(func.distinct(EntAttempt.student_guid)).label(
    #                 "unique_users"
    #             ),
    #             func.avg(EntAttempt.score).label("avg_score"),
    #             func.avg(
    #                 func.extract(
    #                     "epoch", EntAttempt.completed_at - EntAttempt.started_at
    #                 )
    #             )
    #             .filter(EntAttempt.completed_at.isnot(None))
    #             .label("avg_duration"),
    #         ).where(EntAttempt.status == Status.completed)
    #     ).first()

    #     return {
    #         "total_attempts": stats.total_attempts or 0,
    #         "unique_users": stats.unique_users or 0,
    #         "avg_score": float(stats.avg_score or 0),
    #         "avg_duration": float(stats.avg_duration or 0),
    #     }

    # def get_admin_user_stats(self, user_id: UUID) -> dict:
    #     """Get detailed statistics for a specific user"""
    #     stats = self._session.execute(
    #         select(
    #             func.count(EntAttempt.id).label("total_attempts"),
    #             func.avg(EntAttempt.score).label("avg_score"),
    #             func.max(EntAttempt.score).label("best_score"),
    #             func.min(EntAttempt.score).label("worst_score"),
    #             func.avg(
    #                 func.extract(
    #                     "epoch", EntAttempt.completed_at - EntAttempt.started_at
    #                 )
    #             )
    #             .filter(EntAttempt.completed_at.isnot(None))
    #             .label("avg_duration"),
    #         ).where(
    #             EntAttempt.student_guid == user_id,
    #             EntAttempt.status == Status.completed,
    #         )
    #     ).first()

    #     return {
    #         "total_attempts": stats.total_attempts or 0,
    #         "avg_score": float(stats.avg_score or 0),
    #         "best_score": stats.best_score or 0,
    #         "worst_score": stats.worst_score or 0,
    #         "avg_duration": float(stats.avg_duration or 0),
    #     }

    # def get_daily_statistic_by_student(
    #     self, ent_stat_params_dto: EntStatisticGetRepositoryDTO
    # ) -> list[EntStatisticDailyRepositoryDTO]:
    #     """Получить статистику ЕНТ по дням"""
    #     daily_query = (
    #         select(
    #             func.date(EntAttempt.started_at).label("date"),
    #             func.coalesce(func.count(EntAttempt.id), 0).label("tries"),
    #             func.coalesce(func.avg(EntAttempt.score), 0.0).label("avg_score"),
    #             func.coalesce(
    #                 func.avg(
    #                     func.extract(
    #                         "epoch", EntAttempt.completed_at - EntAttempt.started_at
    #                     )
    #                 ),
    #                 0.0,
    #             ).label("avg_spend_time"),
    #         )
    #         .select_from(EntAttempt)
    #         .where(
    #             EntAttempt.student_guid == ent_stat_params_dto.student_guid,
    #             EntAttempt.started_at
    #             >= func.to_timestamp(ent_stat_params_dto.ts_start),
    #             EntAttempt.started_at <= func.to_timestamp(ent_stat_params_dto.ts_end),
    #             EntAttempt.status == "completed",
    #         )
    #         .group_by(func.date(EntAttempt.started_at))
    #         .order_by(func.date(EntAttempt.started_at))
    #     )

    #     daily_results = self._session.execute(daily_query).all()

    #     return [
    #         EntStatisticDailyRepositoryDTO(
    #             date=row.date,
    #             tries=row.tries,
    #             avg_score=float(row.avg_score) if row.avg_score else 0.0,
    #             avg_spend_time=float(row.avg_spend_time) if row.avg_spend_time else 0.0,
    #         )
    #         for row in daily_results
    #     ]

    # def get_answers(self, ent_attempt_id: int) -> list:
    #     """Получить все ответы для попытки (для верификации)"""
    #     answers = (
    #         self._session.query(EntAttemptAnswer)
    #         .filter(EntAttemptAnswer.ent_attempt_id == ent_attempt_id)
    #         .all()
    #     )

    #     logger.info(
    #         "Found %s answers in DB for attempt %s", len(answers), ent_attempt_id
    #     )
    #     for answer in answers:
    #         logger.info(
    #             "   DB Answer: attempt_id=%s, variant_id=%s",
    #             answer.ent_attempt_id,
    #             answer.variant_id,
    #         )

    #     return answers

    def get_completed_attempts_by_period(
        self,
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType = None,
    ) -> list[EntAttempt]:
        """Получить все завершенные попытки ЕНТ за период"""
        from sqlalchemy.orm import joinedload

        additional_filters = []
        if not exam_type:
            additional_filters.append(EntAttempt.exam_type == exam_type)

        join_options = [joinedload(EntAttempt.options)]

        return RepositoryHelpers.get_completed_attempts_by_period(
            session=self._session,
            model_class=EntAttempt,
            student_guid=student_guid,
            start_date=start_date,
            end_date=end_date,
            additional_filters=additional_filters,
            join_options=join_options,
        )

    def get_all_attempts_for_student(self, student_guid: UUID, limit: int | None = None) -> list[EntAttempt]:
        """Получить все попытки студента (история)"""
        query = (
            self._session.query(EntAttempt)
            .options(
                joinedload(EntAttempt.options).joinedload(EntOption.subject),
                joinedload(EntAttempt.subject_combination),
            )
            .filter(EntAttempt.student_guid == student_guid)
            .order_by(EntAttempt.started_at.desc())
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_attempt_with_answers(self, attempt_id: int, student_guid: UUID) -> EntAttempt | None:
        """Получить попытку с ответами и деталями"""
        attempt = (
            self._session.query(EntAttempt)
            .options(
                joinedload(EntAttempt.options).joinedload(EntOption.subject),
                joinedload(EntAttempt.subject_combination),
            )
            .filter(EntAttempt.id == attempt_id, EntAttempt.student_guid == student_guid)
            .first()
        )

        return attempt

    def get_attempt_answers_with_questions(self, attempt_id: int) -> list[EntAttemptAnswer]:
        """Получить все ответы попытки вместе с вопросами и вариантами"""
        logger.info("Getting answers with questions for attempt %s", attempt_id)

        answers = (
            self._session.query(EntAttemptAnswer)
            .options(
                joinedload(EntAttemptAnswer.variant).joinedload(Variant.question).joinedload(Question.subject),
                joinedload(EntAttemptAnswer.variant).joinedload(Variant.question).joinedload(Question.topic),
            )
            .filter(EntAttemptAnswer.ent_attempt_id == attempt_id)
            .all()
        )

        logger.info("Found %s answers for attempt %s", len(answers), attempt_id)

        # Подробное логирование для отладки
        # for i, answer in enumerate(answers):
        #     logger.info(f"Answer {i + 1}:")
        #     logger.info(f"  - Answer ID: {answer.id}")
        #     logger.info(f"  - Variant ID: {answer.variant_id}")

        #     if answer.variant:
        #         logger.info(f"  - Variant type: {type(answer.variant)}")
        #         logger.info(f"  - Variant ID in object: {answer.variant.id}")

        #         if hasattr(answer.variant, "question"):
        #             question = answer.variant.question
        #             if question:
        #                 logger.info(f"  - Question type: {type(question)}")
        #                 logger.info(f"  - Question ID: {question.id}")
        #                 logger.info(
        #                     f"  - Question has subject_id: {hasattr(question, 'subject_id')}"
        #                 )

        #                 if hasattr(question, "subject"):
        #                     subject = question.subject
        #                     if subject:
        #                         logger.info(f"  - Subject type: {type(subject)}")
        #                         logger.info(f"  - Subject name: {subject.name}")
        #                     else:
        #                         logger.warning("  - Question.subject is None")
        #                 else:
        #                     logger.warning("  - Question has no 'subject' attribute")
        #             else:
        #                 logger.warning("  - Variant.question is None")
        #         else:
        #             logger.warning("  - Variant has no 'question' attribute")
        #     else:
        #         logger.warning("  - Answer.variant is None")

        return answers

    def get_best_attempt_for_option(self, user_id: str, ent_option_id: int):
        """Получить лучшую попытку пользователя для варианта ЕНТ"""
        from quiz.models.ent import EntAttempt

        attempts = (
            self._session.query(EntAttempt)
            .filter(
                EntAttempt.student_guid == user_id,
                EntAttempt.ent_option_id == ent_option_id,
                EntAttempt.status == Status.completed,
            )
            .all()
        )

        if not attempts:
            return None

        best_attempt = max(attempts, key=lambda a: a.score if a.score else 0)
        return best_attempt

    def get_attempt_count(self, user_id: str, ent_option_id: int) -> int:
        """Получить количество попыток пользователя для варианта ЕНТ"""
        return RepositoryHelpers.get_attempt_count(
            session=self._session,
            model_class=EntAttempt,
            user_id=user_id,
            filter_field="ent_option_id",
            filter_value=ent_option_id,
        )

    def get_ent_option_ids_with_attempts(self, user_id: str) -> set[int]:
        """Множество ent_option_id, по которым у пользователя есть попытки.

        Один запрос (DISTINCT) вместо поштучной проверки каждого варианта —
        устраняет N+1 (по сессии БД на каждый вариант). Статус не фильтруется,
        совпадает с поведением get_attempt_count.
        """
        rows = (
            self._session.query(EntAttempt.ent_option_id)
            .filter(EntAttempt.student_guid == user_id)
            .distinct()
            .all()
        )
        return {row[0] for row in rows if row[0] is not None}

    def get_user_total_attempts(self, user_id: str) -> int:
        """Получить общее количество попыток пользователя во всех вариантах ЕНТ"""
        return RepositoryHelpers.get_user_total_attempts(
            session=self._session,
            model_class=EntAttempt,
            user_id=user_id,
        )

    def get_question_times_by_period(
        self,
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
        exam_type: ExamType = None,
    ) -> list[float]:
        """Получить средние времена на вопросы для ENT для расчета медианы"""
        attempts = self.get_completed_attempts_by_period(
            student_guid=student_guid,
            start_date=start_date,
            end_date=end_date,
            exam_type=exam_type,
        )

        times = []
        for attempt in attempts:
            attempt_stats = self.get_attempt_statistic(attempt.id, None)
            total_questions = (
                self._session.query(EntOptionQuestion)
                .filter(EntOptionQuestion.ent_option_id == attempt.ent_option_id)
                .count()
            )

            if total_questions > 0 and attempt_stats.spend_time > 0:
                avg_time = attempt_stats.spend_time / total_questions
                times.append(float(avg_time))

        logger.info("Found %s ENT attempt times for median calculation", len(times))
        return times

    def get_all_completed_attempts(self, student_id: UUID, exam_type: ExamType) -> list[EntAttempt]:
        """Получить все завершенные попытки ЕНТ за все время"""
        logger.info("Getting all completed ENT attempts for student %s", student_id)

        additional_filters = []
        if exam_type is not None:
            additional_filters.append(EntAttempt.exam_type == exam_type)

        query = (
            self._session.query(EntAttempt)
            .options(
                joinedload(EntAttempt.options),
                joinedload(EntAttempt.subject_combination),
            )
            .filter(
                EntAttempt.student_guid == student_id,
                EntAttempt.status == Status.completed,
            )
        )

        if additional_filters:
            query = query.filter(*additional_filters)

        return query.all()

    def get_attempt_subjects_statistics(self, student_id: UUID, exam_type: ExamType) -> dict[int, dict[str, Any]]:
        """Получить статистику по предметам для всех попыток ЕНТ"""
        logger.info("Getting ENT subject statistics for student %s", student_id)

        answers_query = (
            self._session.query(EntAttemptAnswer, Variant, Question, Subject)
            .join(Variant, Variant.id == EntAttemptAnswer.variant_id)
            .join(Question, Question.id == Variant.question_id)
            .join(Subject, Subject.id == Question.subject_id)
            .join(EntAttempt, EntAttempt.id == EntAttemptAnswer.ent_attempt_id)
            .filter(
                EntAttempt.student_guid == student_id,
                EntAttempt.status == Status.completed,
            )
        )

        if exam_type:
            answers_query = answers_query.filter(EntAttempt.exam_type == exam_type)

        answers = answers_query.all()

        subject_stats = {}
        for _answer, variant, _question, subject in answers:
            subject_id = subject.id
            if subject_id not in subject_stats:
                subject_stats[subject_id] = {
                    "subject_id": subject_id,
                    "subject_name": subject.name,
                    "total_questions": 0,
                    "correct_answers": 0,
                }

            subject_stats[subject_id]["total_questions"] += 1
            if variant.is_correct:
                subject_stats[subject_id]["correct_answers"] += 1

        return subject_stats

    def count_practice_ents_above_threshold(
        self,
        student_guid: UUID,
        start_utc: datetime,
        end_utc: datetime,
        threshold: float,
    ) -> int:
        attempts = (
            self._session.query(EntAttempt)
            .filter(
                EntAttempt.student_guid == student_guid,
                EntAttempt.exam_type == ExamType.by_subject,
                EntAttempt.status == Status.completed,
                EntAttempt.completed_at >= start_utc,
                EntAttempt.completed_at <= end_utc,
            )
            .all()
        )
        count = 0
        for attempt in attempts:
            stats = self.get_attempt_statistic(attempt.id, None)
            if stats and stats.total_questions > 0 and (stats.correct / stats.total_questions) * 100 > threshold:
                count += 1
        return count

    def count_full_ents_above_threshold(
        self,
        student_guid: UUID,
        start_utc: datetime,
        end_utc: datetime,
        threshold: float,
    ) -> int:
        attempts = (
            self._session.query(EntAttempt)
            .filter(
                EntAttempt.student_guid == student_guid,
                EntAttempt.exam_type == ExamType.full_exam,
                EntAttempt.status == Status.completed,
                EntAttempt.completed_at >= start_utc,
                EntAttempt.completed_at <= end_utc,
            )
            .all()
        )
        count = 0
        for attempt in attempts:
            stats = self.get_attempt_statistic(attempt.id, None)
            if stats and stats.total_questions > 0 and (stats.correct / stats.total_questions) * 100 > threshold:
                count += 1
        return count

    def get_ent_attempts_for_feed(self, student_guid: UUID, limit: int, offset: int) -> tuple[list[EntAttempt], int]:
        """Получить завершённые попытки ЕНТ для ленты (все типы)."""
        query = (
            self._session.query(EntAttempt)
            .filter(
                EntAttempt.student_guid == student_guid,
                EntAttempt.status == Status.completed,
            )
            .order_by(EntAttempt.completed_at.desc())
        )
        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total
