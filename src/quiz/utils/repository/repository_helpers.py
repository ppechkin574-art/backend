import logging
from datetime import date, datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Query, Session

from quiz.dtos.enums import Status

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RepositoryHelpers:
    @staticmethod
    def get_completed_attempts_by_period(
        session: Session,
        model_class: type[T],
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
        status_field_name: str = "status",
        completed_status: Any = Status.completed,
        additional_filters: list | None = None,
        join_options: list | None = None,
        completed_at_field: str = "completed_at",
    ) -> list[T]:
        """Method for getting completed attempts by period"""
        logger.info(
            "Getting completed attempts for student %s from %s to %s",
            student_guid,
            start_date,
            end_date,
        )

        query: Query = session.query(model_class)

        if join_options:
            for option in join_options:
                query = query.options(option)

        filters = [
            model_class.student_guid == student_guid,
            getattr(model_class, status_field_name) == completed_status,
            getattr(model_class, completed_at_field) >= start_date,
            getattr(model_class, completed_at_field) <= end_date,
        ]

        if additional_filters:
            filters.extend(additional_filters)

        if len(filters) == 1:
            query = query.filter(filters[0])
        elif len(filters) > 1:
            query = query.filter(and_(*filters))

        results = query.all()
        logger.info("Found %s completed attempts", len(results))
        return results

    @staticmethod
    def get_completed_dates(
        session: Session,
        model_class: type[T],
        student_guid: UUID,
        completed_at_field: str = "completed_at",
        status_field_name: str = "status",
        completed_status: Any = Status.completed,
    ) -> set[date]:
        """Method for getting completed dates"""
        logger.info("Getting completed dates for student %s", student_guid)

        result = (
            session.execute(
                select(func.date(getattr(model_class, completed_at_field)))
                .where(
                    model_class.student_guid == student_guid,
                    getattr(model_class, status_field_name) == completed_status,
                    getattr(model_class, completed_at_field).isnot(None),
                )
                .distinct()
            )
            .scalars()
            .all()
        )

        dates = set(result)
        logger.info("Found %s completed dates", len(dates))
        return dates

    @staticmethod
    def get_user_total_attempts(
        session: Session,
        model_class: type[T],
        user_id: str,
        additional_filters: list | None = None,
    ) -> int:
        """Method for getting user total attempts"""
        query = session.query(model_class).filter(model_class.student_guid == user_id)

        if additional_filters:
            query = query.filter(and_(*additional_filters))

        return query.count()

    @staticmethod
    def get_attempt_count(
        session: Session,
        model_class: type[T],
        user_id: str,
        filter_field: str,
        filter_value: Any,
        student_guid_field: str = "student_guid",
    ) -> int:
        """Method for getting attempt count"""
        return (
            session.query(model_class)
            .filter(
                getattr(model_class, student_guid_field) == user_id,
                getattr(model_class, filter_field) == filter_value,
            )
            .count()
        )

    # @staticmethod
    # def calculate_basic_attempt_statistics(
    #     session: Session,
    #     attempt_id: int,
    #     model_class: type[T],
    #     question_relation: str,
    #     answer_relation: str,
    #     variant_relation: str = "variants",
    #     spend_time_field: str = "spend_time",
    #     correct_field: str = "is_correct",
    #     variant_id_field: str = "variant_id",
    # ) -> dict[str, Any]:
    #     """Method for calculating basic attempt statistics"""

    #     attempt = (
    #         session.query(model_class)
    #         .options(
    #             joinedload(getattr(model_class, question_relation)).joinedload(answer_relation),
    #             joinedload(getattr(model_class, question_relation))
    #             .joinedload(question_relation)
    #             .joinedload(variant_relation),
    #         )
    #         .filter(model_class.id == attempt_id)
    #         .first()
    #     )

    #     if not attempt:
    #         return {
    #             "correct": 0,
    #             "incorrect": 0,
    #             "skipped": 0,
    #             "total_questions": 0,
    #             "spend_time": 0,
    #             "score": 0,
    #         }

    #     questions = getattr(attempt, question_relation, [])
    #     total_questions = len(questions)

    #     correct = 0
    #     incorrect = 0
    #     skipped = 0
    #     total_spend_time = 0

    #     for question in questions:
    #         spend_time = getattr(question, spend_time_field, 0)
    #         total_spend_time += spend_time

    #         answers = getattr(question, answer_relation, [])
    #         if not answers:
    #             skipped += 1
    #             continue

    #         question_entity = getattr(question, "question", question)
    #         variants = getattr(question_entity, variant_relation, [])
    #         correct_variant_ids = {v.id for v in variants if getattr(v, correct_field, False)}

    #         chosen_variant_ids = {
    #             getattr(a, variant_id_field) for a in answers if getattr(a, variant_id_field) is not None
    #         }

    #         if correct_variant_ids and chosen_variant_ids == correct_variant_ids:
    #             correct += 1
    #         else:
    #             incorrect += 1

    #     score = correct  # 1 if correct else 0

    #     return {
    #         "correct": correct,
    #         "incorrect": incorrect,
    #         "skipped": skipped,
    #         "total_questions": total_questions,
    #         "spend_time": int(total_spend_time),
    #         "score": score,
    #     }

    @staticmethod
    def get_question_times_by_period(
        session: Session,
        attempt_model_class: type[T],
        question_model_class: type[T],
        join_conditions: dict[str, Any],
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
        spend_time_field: str = "spend_time",
        additional_filters: list | None = None,
    ) -> list[float]:
        """Method for getting question times by period"""
        query = session.query(getattr(question_model_class, spend_time_field))

        for _join_attr, join_value in join_conditions.items():
            query = query.join(join_value)

        filters = [
            attempt_model_class.student_guid == student_guid,
            attempt_model_class.status == Status.completed,
            attempt_model_class.completed_at >= start_date,
            attempt_model_class.completed_at <= end_date,
            getattr(question_model_class, spend_time_field) > 0,
        ]

        if additional_filters:
            filters.extend(additional_filters)

        query = query.filter(and_(*filters))

        times = [float(time[0]) for time in query.all()]
        logger.info("Found %s non-zero question times", len(times))
        return times
