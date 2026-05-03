import logging
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

# from sqlalchemy import literal_column
from sqlalchemy.orm import Session, joinedload

# from sqlalchemy.sql import case, func, select
# from quiz.converters import (
#     to_test_details_dto_from_test_attempt,
#     to_topic_statistic_service_dto,
# )
from quiz.dtos.enums import Status
from quiz.dtos.questions import QuestionRepositoryDTO

# from quiz.dtos.statistic import (
#     TopicStatisticDailyRepositoryDTO,
#     TopicStatisticGetServiceDTO,
#     TopicStatisticRepositoryDTO,
#     TopicStatisticServiceDTO,
# )
from quiz.dtos.trainer_attempt_answers import (
    TrainerAttemptAnswerCreateRepositoryDTO,
    TrainerAttemptAnswerRepositoryDTO,
)
from quiz.dtos.trainer_attempt_questions import TrainerAttemptQuestionRepositoryDTO
from quiz.dtos.trainer_attempts import (
    TrainerAttemptCreateRepositoryDTO,
    TrainerAttemptRepositoryDTO,
    TrainerAttemptServiceDTO,
)
from quiz.dtos.trainers import TrainerRepositoryDTO
from quiz.exceptions import TrainerAttemptNotExist, TrainerNotFound
from quiz.models.edu_content import Hint, Question, Subject, Topic, Variant
from quiz.models.text_blocks import TextBlockLink
from quiz.models.trainer import (
    Trainer,
    TrainerAttempt,
    TrainerAttemptAnswer,
    TrainerAttemptQuestion,
    TrainerQuestion,
)
from quiz.utils.attempt_statistic_calculator import (
    AttemptStatisticCalculator,
)
from quiz.utils.init import RepositoryHelpers

logger = logging.getLogger(__name__)


class TrainerAttemptRepositoryInterface(Protocol):
    def create(self, test: TrainerAttemptCreateRepositoryDTO) -> TrainerAttemptRepositoryDTO:
        """
        Create TrainerAttempt.

        Args:
            test: Parameters to create test.

        Returns:
            TrainerAttemptRepositoryDTO: Test attempt.
        """
        raise NotImplementedError

    def add_question(self, test_attempt_id: int, question_id: int) -> TrainerAttemptQuestionRepositoryDTO:
        """
        Add question to test attempt.

        Args:
            test_attempt_id: ID of Test Attempt to which question is added.
            question_id: ID of a question which is added to Test Attempt.

        Returns:
            TrainerAttemptQuestionRepositoryDTO: Created test attempt question.
        """
        raise NotImplementedError

    def get_by_question_id(self, test_attempt_question_id: int) -> TrainerAttemptRepositoryDTO:
        """
        Get TrainerAttempt by test_attempt_question_id.

        Args:
            test_attempt_question_id: ID of a TrainerAttemptQuestion.

        Returns:
            TrainerAttemptRepositoryDTO: Test attempt.
        """
        raise NotImplementedError

    # def get_answers(
    #     self, test_attempt_question_id: int
    # ) -> list[TrainerAttemptAnswerRepositoryDTO]:
    #     """
    #     Get answers for test_attempt_question_id.

    #     Args:
    #         test_attempt_question_id: ID of a TrainerAttemptQuestion.

    #     Returns:
    #         list[TrainerAttemptAnswerRepositoryDTO]: Array of answers.
    #     """
    #     raise NotImplementedError

    def create_answer(self, answer: TrainerAttemptAnswerCreateRepositoryDTO) -> TrainerAttemptAnswerRepositoryDTO:
        """
        Create answer for question in test attempt.

        Args:
            answer: Answer parameters.

        Returns:
            TrainerAttemptAnswerRepositoryDTO: Created answer.
        """
        raise NotImplementedError

    # def get_gt_id(self, id_: int, limit: int) -> list[TrainerAttemptServiceDTO]:
    #     """
    #     Gets test attempt by written query.

    #     Args:
    #         id_ (int): Greater than id border.
    #         limit (int): limiting query.

    #     Returns:
    #         list[TrainerAttemptServiceDTO]: Test attempt rows with id higher than id_.
    #     """
    #     raise NotImplementedError

    def get_active_for_student(self, student_guid: UUID, topic_id: int) -> TrainerAttemptRepositoryDTO | None:
        """Возвращает in_progress попытку или None."""
        raise NotImplementedError

    def get_with_questions(self, test_attempt_id: int) -> TrainerAttemptServiceDTO:
        """Возвращает попытку с вопросами и вариантами (используется для выдачи клиенту)."""
        raise NotImplementedError

    # def get_answered_question_ids_by_student(self, student_id: str) -> list:
    #     raise NotImplementedError

    def get_question_by_id(self, test_attempt_question_id: int) -> TrainerAttemptQuestion:
        raise NotImplementedError

    # def get_topic_statistic(
    #     self, stat_params: TopicStatisticGetServiceDTO
    # ) -> TopicStatisticServiceDTO:
    #     raise NotImplementedError

    def update_question_spend_time(self, test_attempt_question_id: int, spend_time: int) -> None:
        raise NotImplementedError

    def get_trainer_by_topic(self, topic_id: int) -> TrainerRepositoryDTO:
        raise NotImplementedError

    def get_questions_by_trainer(self, trainer_id: int) -> list[QuestionRepositoryDTO]:
        raise NotImplementedError

    def finish_and_score(self, test_attempt_id: int) -> tuple[TrainerAttemptRepositoryDTO, dict]:
        """Подсчитать результат, пометить completed, вернуть обновлённую запись и статистику."""
        raise NotImplementedError

    def get_by_id(self, test_attempt_id: int) -> TrainerAttemptRepositoryDTO | None:
        raise NotImplementedError

    def get_trainers_by_topic_id(self, topic_id: int) -> list[TrainerRepositoryDTO]:
        raise NotImplementedError

    def get_by_topic_id(self, topic_id: int) -> list[TrainerRepositoryDTO]:
        raise NotImplementedError


class TrainerAttemptRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, test: TrainerAttemptCreateRepositoryDTO) -> TrainerAttemptRepositoryDTO:
        logger.info(
            "Creating trainer attempt for student: %s, trainer: %s",
            test.student_guid,
            test.trainer_id,
        )

        raw = test.model_dump()
        allowed = {
            "student_guid",
            "trainer_id",
            "score",
            "status",
            "started_at",
            "completed_at",
        }
        filtered = {k: v for k, v in raw.items() if k in allowed and v is not None}
        test_attempt = TrainerAttempt(**filtered)
        self._session.add(test_attempt)
        self._session.flush()
        self._session.refresh(test_attempt)

        logger.info("Created trainer attempt with ID: %s", test_attempt.id)
        return TrainerAttemptRepositoryDTO.model_validate(test_attempt)

    def add_question(self, test_id: int, question_id: int) -> TrainerAttemptQuestionRepositoryDTO:
        logger.info("Adding question %s to attempt %s", question_id, test_id)

        question = TrainerAttemptQuestion(trainer_attempt_id=test_id, question_id=question_id, spend_time=0)
        self._session.add(question)
        self._session.flush()

        logger.info("Added question to attempt: TAQ ID = %s", question.id)
        return TrainerAttemptQuestionRepositoryDTO.model_validate(question)

    def get_by_question_id(self, test_attempt_question_id: int) -> TrainerAttemptRepositoryDTO:
        logger.info(
            "Searching for TrainerAttempt with TrainerAttemptQuestion.id = %s",
            test_attempt_question_id,
        )

        taq = (
            self._session.query(TrainerAttemptQuestion)
            .filter(TrainerAttemptQuestion.id == test_attempt_question_id)
            .one_or_none()
        )

        if not taq:
            logger.exception("TrainerAttemptQuestion with id %s not found", test_attempt_question_id)
            raise TrainerAttemptNotExist(f"TrainerAttemptQuestion with id {test_attempt_question_id} not found")

        result = (
            self._session.query(TrainerAttempt)
            .options(
                joinedload(TrainerAttempt.questions).options(
                    joinedload(TrainerAttemptQuestion.question).options(
                        joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                        joinedload(Question.link).joinedload(TextBlockLink.blocks),
                        joinedload(Question.hint).joinedload(Hint.link).joinedload(TextBlockLink.blocks),
                    ),
                    joinedload(TrainerAttemptQuestion.answers).joinedload(TrainerAttemptAnswer.variant),
                )
            )
            .filter(TrainerAttempt.id == taq.trainer_attempt_id)
            .one_or_none()
        )

        if not result:
            logger.exception("TrainerAttempt not found for id %s", taq.trainer_attempt_id)
            raise TrainerAttemptNotExist(f"TrainerAttempt not found for id {taq.trainer_attempt_id}")

        logger.info("Found attempt: %s with %s questions", result.id, len(result.questions))
        return TrainerAttemptRepositoryDTO.custom(result)

    # def get_answers(
    #     self, test_attempt_question_id: int
    # ) -> list[TrainerAttemptAnswerRepositoryDTO]:
    #     logger.info("Getting answers for question: %s", test_attempt_question_id)

    #     q = self._session.query(TrainerAttemptAnswer).join(TrainerAttemptQuestion)
    #     q = q.filter(
    #         TrainerAttemptQuestion.id == test_attempt_question_id,
    #         TrainerAttemptAnswer.variant_id is not None,
    #     )

    #     answers = [
    #         TrainerAttemptAnswerRepositoryDTO.model_validate(row) for row in q.all()
    #     ]

    #     logger.info(
    #         "Found %s answers for question %s", len(answers), test_attempt_question_id
    #     )
    #     return answers

    def create_answer(self, answer: TrainerAttemptAnswerCreateRepositoryDTO) -> TrainerAttemptAnswerRepositoryDTO:
        logger.info(
            "Creating answer for question: %s, variant: %s",
            answer.trainer_attempt_question_id,
            answer.variant_id,
        )

        answer_obj = TrainerAttemptAnswer(**answer.model_dump())
        self._session.add(answer_obj)
        self._session.flush()

        logger.info("Created answer with ID: %s", answer_obj.id)
        return TrainerAttemptAnswerRepositoryDTO.model_validate(answer_obj)

    def update_question_spend_time(self, test_attempt_question_id: int, spend_time: int):
        logger.info(
            "Updating spend time for question %s to %s seconds",
            test_attempt_question_id,
            spend_time,
        )

        (
            self._session.query(TrainerAttemptQuestion)
            .where(TrainerAttemptQuestion.id == test_attempt_question_id)
            .update({"spend_time": spend_time})
        )
        self._session.flush()

        logger.info("Updated spend time for question %s", test_attempt_question_id)

    # def get_gt_id(self, id_: int, limit: int) -> list[TrainerAttemptServiceDTO]:
    #     q = self._session.query(TrainerAttempt)
    #     joined = joinedload(TrainerAttempt.questions)
    #     joined = joined.joinedload(TrainerAttemptQuestion.answers)
    #     joined = joined.joinedload(TrainerAttemptAnswer.variant)
    #     joined = joined.joinedload(Variant.question)
    #     q = q.options(joinedload(TrainerAttempt.topic), joined)
    #     q = q.filter(TrainerAttempt.id > id_)
    #     q = q.limit(limit)
    #     instances = q.all()
    #     return [to_test_details_dto_from_test_attempt(instance) for instance in instances]

    def get_active_for_student(self, student_guid: UUID, topic_id: int) -> TrainerAttemptServiceDTO | None:
        instance = (
            self._get_base_query()
            .options(joinedload(TrainerAttempt.trainer))
            .filter(
                TrainerAttempt.student_guid == student_guid,
                TrainerAttempt.trainer.has(Trainer.topic_id == topic_id),
                TrainerAttempt.status == Status.in_progress,
            )
            .one_or_none()
        )

        return TrainerAttemptRepositoryDTO.custom(instance) if instance else None

    def get_with_questions(self, test_attempt_id: int) -> TrainerAttemptRepositoryDTO:
        test_attempt = self._get_base_query().filter(TrainerAttempt.id == test_attempt_id).one()
        return TrainerAttemptRepositoryDTO.custom(test_attempt)

    def finish_and_score(self, test_attempt_id: int) -> tuple[TrainerAttemptRepositoryDTO, dict]:
        logger.info("Finishing and scoring attempt %s", test_attempt_id)

        q = (
            self._session.query(TrainerAttempt)
            .options(
                joinedload(TrainerAttempt.questions).options(
                    joinedload(TrainerAttemptQuestion.question).options(
                        joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                        joinedload(Question.link).joinedload(TextBlockLink.blocks),
                        joinedload(Question.hint).joinedload(Hint.link).joinedload(TextBlockLink.blocks),
                    ),
                    joinedload(TrainerAttemptQuestion.answers).joinedload(TrainerAttemptAnswer.variant),
                )
            )
            .filter(TrainerAttempt.id == test_attempt_id)
        )
        attempt = q.one()

        score = 0
        correct_answers = 0
        incorrect_answers = 0
        total_questions = len(attempt.questions)

        logger.info("Scoring %s questions...", total_questions)

        for _i, taq in enumerate(attempt.questions):
            correct_variant_ids = {v.id for v in taq.question.variants if v.is_correct}
            chosen_variant_ids = {a.variant_id for a in taq.answers if a.variant_id is not None}

            # logger.info(
            #     f"   Question {i+1}: correct variants: {correct_variant_ids}, chosen: {chosen_variant_ids}"
            # )

            if correct_variant_ids and chosen_variant_ids == correct_variant_ids:
                score += 1.0
                correct_answers += 1
                # logger.info(f"   Question {i+1}: CORRECT")
            elif chosen_variant_ids:
                incorrect_answers += 1
                # logger.info(f"   Question {i+1}: INCORRECT")
            else:
                # logger.info(f"   Question {i+1}: SKIPPED")
                continue

            for a in taq.answers:
                a.is_correct = bool(a.variant and a.variant.is_correct)
                self._session.add(a)

        attempt.completed_at = datetime.now(UTC).replace(tzinfo=None)
        attempt.status = Status.completed
        attempt.score = score

        self._session.add(attempt)
        self._session.flush()

        statistics = {
            "correct_answers": correct_answers,
            "incorrect_answers": incorrect_answers,
            "max_score": total_questions,
        }

        logger.info(
            "Scoring completed: score=%s, correct=%s, incorrect=%s, max_score=%s",
            score,
            correct_answers,
            incorrect_answers,
            total_questions,
        )

        return TrainerAttemptRepositoryDTO.custom(attempt), statistics

    def get_completed_dates(self, student_guid: UUID) -> set[date]:
        """Получает все даты, когда пользователь завершал тренажеры"""
        return RepositoryHelpers.get_completed_dates(
            session=self._session,
            model_class=TrainerAttempt,
            student_guid=student_guid,
        )

    def get_question_by_id(self, test_attempt_question_id: int) -> TrainerAttemptQuestion:
        logger.info("Getting question by ID: %s", test_attempt_question_id)

        question = (
            self._session.query(TrainerAttemptQuestion)
            .filter(TrainerAttemptQuestion.id == test_attempt_question_id)
            .one_or_none()
        )

        if question:
            logger.info("Found question: %s", question.id)
        else:
            logger.warning("Question %s not found", test_attempt_question_id)

        return question

    def get_by_id(self, test_attempt_id: int) -> TrainerAttemptRepositoryDTO | None:
        logger.info("Getting attempt by ID: %s", test_attempt_id)

        attempt = self._get_base_query().filter(TrainerAttempt.id == test_attempt_id).one_or_none()

        if attempt:
            logger.info(
                "Found attempt: %s with %s questions",
                attempt.id,
                len(attempt.questions),
            )
            return TrainerAttemptRepositoryDTO.custom(attempt)

        logger.warning("Attempt %s not found", test_attempt_id)
        return None

    # def get_answered_question_ids_by_student(self, student_id: str) -> list:
    #     q = (
    #         self._session.query(Question.id)
    #         .join(Variant, Variant.question_id == Question.id)
    #         .join(TrainerAttemptAnswer, TrainerAttemptAnswer.variant_id == Variant.id)
    #         .join(
    #             TrainerAttemptQuestion,
    #             TrainerAttemptQuestion.id == TrainerAttemptAnswer.trainer_attempt_question_id,
    #         )
    #         .join(
    #             TrainerAttempt,
    #             TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
    #         )
    #         .filter(
    #             TrainerAttempt.student_guid == student_id,
    #             TrainerAttemptAnswer.is_correct.is_(True),
    #         )
    #         .distinct()
    #     )
    #     return [r[0] for r in q.all()]

    # def get_topic_statistic(self, stat_params: TopicStatisticGetServiceDTO) -> TopicStatisticServiceDTO:
    #     overall_stats = self._get_topic_statistic_overall(stat_params)

    #     daily_stats = self.get_daily_topic_statistic(stat_params)

    #     return to_topic_statistic_service_dto(overall_stats, daily_stats)

    # def _get_topic_statistic_overall(
    #     self, stat_params: TopicStatisticGetServiceDTO
    # ) -> TopicStatisticRepositoryDTO:
    #     logger.info(
    #         "Building overall statistic query for student: %s, topic: %s, time range: %s to %s",
    #         stat_params.student_guid,
    #         stat_params.topic_id,
    #         stat_params.ts_start,
    #         stat_params.ts_end,
    #     )
    #     answer_scores = (
    #         select(
    #             TrainerAttemptQuestion.id.label("taq_id"),
    #             func.sum(Variant.weight).label("total_weight"),
    #             func.count(Variant.id).label("variant_count"),
    #             case(
    #                 (
    #                     func.count(TrainerAttemptAnswer.variant_id) == 0,
    #                     literal_column("'skiped'"),
    #                 ),
    #                 else_=case(
    #                     (func.sum(Variant.weight) == 1.0, literal_column("'correct'")),
    #                     (func.sum(Variant.weight) > 1.0, literal_column("'correct'")),
    #                     (
    #                         func.sum(Variant.weight) == 0.0,
    #                         literal_column("'incorrect'"),
    #                     ),
    #                     else_=literal_column("'partial_correct'"),
    #                 ),
    #             ).label("result"),
    #             TrainerAttemptQuestion.spend_time.label("spend_time"),
    #         )
    #         .select_from(TrainerAttemptAnswer)
    #         .join(
    #             TrainerAttemptQuestion,
    #             TrainerAttemptQuestion.id
    #             == TrainerAttemptAnswer.trainer_attempt_question_id,
    #         )
    #         .join(
    #             TrainerAttempt,
    #             TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
    #         )
    #         .join(Question, Question.id == TrainerAttemptQuestion.question_id)
    #         .join(Variant, Variant.id == TrainerAttemptAnswer.variant_id)
    #         .where(
    #             TrainerAttempt.student_guid == stat_params.student_guid,
    #             TrainerAttempt.status == Status.completed,
    #             Question.topic_id == stat_params.topic_id,
    #             TrainerAttempt.started_at >= func.to_timestamp(stat_params.ts_start),
    #             TrainerAttempt.started_at <= func.to_timestamp(stat_params.ts_end),
    #         )
    #         .group_by(TrainerAttemptQuestion.id)
    #         .cte("answer_scores")
    #     )

    #     result = self._session.execute(
    #         select(
    #             func.count(answer_scores.c.taq_id).label("total"),
    #             func.count()
    #             .filter(answer_scores.c.result == "correct")
    #             .label("correct"),
    #             func.count()
    #             .filter(answer_scores.c.result == "partial_correct")
    #             .label("partial_correct"),
    #             func.count().filter(answer_scores.c.result == "skiped").label("skiped"),
    #             func.count()
    #             .filter(answer_scores.c.result == "incorrect")
    #             .label("incorrect"),
    #             func.coalesce(func.avg(answer_scores.c.spend_time), 0.0).label(
    #                 "avg_spend_time"
    #             ),
    #         )
    #     ).first()
    #     logger.info(
    #         "Query result: total=%s, correct=%s, incorrect=%s, avg_time=%s",
    #         result.total,
    #         result.correct,
    #         result.incorrect,
    #         result.avg_spend_time,
    #     )
    #     return TopicStatisticRepositoryDTO.model_validate(result._mapping)

    def get_trainer_by_topic(self, topic_id: int):
        q = self._session.query(Trainer).filter(Trainer.topic_id == topic_id).one_or_none()
        if q:
            return TrainerRepositoryDTO.model_validate(q, from_attributes=True)
        raise TrainerNotFound(f"Trainer not found for topic {topic_id}")

    def get_questions_by_trainer(self, trainer_id: int) -> list[QuestionRepositoryDTO]:
        trainer = self._session.query(Trainer).filter(Trainer.id == trainer_id).one_or_none()
        if not trainer:
            raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

        q = (
            self._session.query(Question)
            .options(
                joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.hint).joinedload(Hint.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.link).joinedload(TextBlockLink.blocks),
                joinedload(Question.trainer_questions),
            )
            .filter(
                Question.trainer_questions.any(TrainerQuestion.trainer_id == trainer_id),
                Question.topic_id == trainer.topic_id,
            )
            .all()
        )
        return [QuestionRepositoryDTO.custom(item) for item in q]

    def get_trainers_by_topic_id(self, topic_id: int) -> list[TrainerRepositoryDTO]:
        """Получить все тренажеры по topic_id"""
        trainers = self._session.query(Trainer).filter_by(topic_id=topic_id).all()
        return [TrainerRepositoryDTO.model_validate(trainer) for trainer in trainers]

    def get_by_topic_id(self, topic_id: int) -> list[TrainerRepositoryDTO]:
        """Получить все тренажеры по topic_id (алиас для get_trainers_by_topic_id)"""
        return self.get_trainers_by_topic_id(topic_id)

    def _get_base_query(self):
        return self._session.query(TrainerAttempt).options(
            joinedload(TrainerAttempt.questions).options(
                joinedload(TrainerAttemptQuestion.question).options(
                    joinedload(Question.variants).joinedload(Variant.link).joinedload(TextBlockLink.blocks),
                    joinedload(Question.link).joinedload(TextBlockLink.blocks),
                    joinedload(Question.hint).joinedload(Hint.link).joinedload(TextBlockLink.blocks),
                ),
                joinedload(TrainerAttemptQuestion.answers).joinedload(TrainerAttemptAnswer.variant),
            )
        )

    # def get_daily_topic_statistic(
    #     self, stat_params: TopicStatisticGetServiceDTO
    # ) -> list[TopicStatisticDailyRepositoryDTO]:
    #     """Получить статистику тренажеров по дням"""

    #     answer_scores = (
    #         select(
    #             func.date(TrainerAttempt.started_at).label("date"),
    #             TrainerAttemptQuestion.id.label("taq_id"),
    #             func.sum(Variant.weight).label("total_weight"),
    #             func.count(Variant.id).label("variant_count"),
    #             case(
    #                 (
    #                     func.count(TrainerAttemptAnswer.variant_id) == 0,
    #                     literal_column("'skiped'"),
    #                 ),
    #                 else_=case(
    #                     (func.sum(Variant.weight) == 1.0, literal_column("'correct'")),
    #                     (func.sum(Variant.weight) > 1.0, literal_column("'correct'")),
    #                     (
    #                         func.sum(Variant.weight) == 0.0,
    #                         literal_column("'incorrect'"),
    #                     ),
    #                     else_=literal_column("'partial_correct'"),
    #                 ),
    #             ).label("result"),
    #             TrainerAttemptQuestion.spend_time.label("spend_time"),
    #         )
    #         .select_from(TrainerAttemptAnswer)
    #         .join(
    #             TrainerAttemptQuestion,
    #             TrainerAttemptQuestion.id
    #             == TrainerAttemptAnswer.trainer_attempt_question_id,
    #         )
    #         .join(
    #             TrainerAttempt,
    #             TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
    #         )
    #         .join(Question, Question.id == TrainerAttemptQuestion.question_id)
    #         .join(Variant, Variant.id == TrainerAttemptAnswer.variant_id)
    #         .where(
    #             TrainerAttempt.student_guid == stat_params.student_guid,
    #             TrainerAttempt.status == Status.completed,
    #             Question.topic_id == stat_params.topic_id,
    #             TrainerAttempt.started_at >= func.to_timestamp(stat_params.ts_start),
    #             TrainerAttempt.started_at <= func.to_timestamp(stat_params.ts_end),
    #         )
    #         .group_by(func.date(TrainerAttempt.started_at), TrainerAttemptQuestion.id)
    #         .cte("answer_scores")
    #     )

    #     daily_stats = self._session.execute(
    #         select(
    #             answer_scores.c.date,
    #             func.count(answer_scores.c.taq_id).label("total"),
    #             func.count()
    #             .filter(answer_scores.c.result == "correct")
    #             .label("correct"),
    #             func.count()
    #             .filter(answer_scores.c.result == "partial_correct")
    #             .label("partial_correct"),
    #             func.count().filter(answer_scores.c.result == "skiped").label("skiped"),
    #             func.count()
    #             .filter(answer_scores.c.result == "incorrect")
    #             .label("incorrect"),
    #             func.coalesce(func.avg(answer_scores.c.spend_time), 0.0).label(
    #                 "avg_spend_time"
    #             ),
    #         )
    #         .group_by(answer_scores.c.date)
    #         .order_by(answer_scores.c.date)
    #     ).all()

    #     return [
    #         TopicStatisticDailyRepositoryDTO(
    #             date=row.date,
    #             total=row.total,
    #             correct=row.correct,
    #             partial_correct=row.partial_correct,
    #             incorrect=row.incorrect,
    #             skiped=row.skiped,
    #             avg_spend_time=float(row.avg_spend_time) if row.avg_spend_time else 0.0,
    #         )
    #         for row in daily_stats
    #     ]

    def get_question_by_attempt_question_id(self, trainer_attempt_question_id: int):
        """Получить вопрос с вариантами по ID вопроса в попытке"""
        ta_question = (
            self._session.query(TrainerAttemptQuestion)
            .options(
                joinedload(TrainerAttemptQuestion.question)
                .joinedload(Question.variants)
                .joinedload(Variant.link)
                .joinedload(TextBlockLink.blocks)
            )
            .filter(TrainerAttemptQuestion.id == trainer_attempt_question_id)
            .first()
        )

        if ta_question and ta_question.question:
            return QuestionRepositoryDTO.custom(ta_question.question)
        return None

    # def get_answers_for_question(self, trainer_attempt_question_id: int) -> list:
    #     """Получить все ответы для вопроса (для верификации)"""
    #     try:
    #         answers = (
    #             self._session.query(TrainerAttemptAnswer)
    #             .filter(TrainerAttemptAnswer.trainer_attempt_question_id == trainer_attempt_question_id)
    #             .all()
    #         )

    #         logger.info(
    #             "Found %s answers in DB for question %s",
    #             len(answers),
    #             trainer_attempt_question_id,
    #         )
    #         for answer in answers:
    #             logger.info(
    #                 "   DB Answer: id=%s, question_id=%s, variant_id=%s",
    #                 answer.id,
    #                 answer.trainer_attempt_question_id,
    #                 answer.variant_id,
    #             )

    #         return answers
    #     except Exception as e:
    #         logger.exception(
    #             "Error getting answers for question %s: %s",
    #             trainer_attempt_question_id,
    #             e,
    #         )
    #         return []

    def get_completed_attempts_by_period(
        self,
        student_guid: UUID,
        topic_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[TrainerAttempt]:
        """Получить все завершенные попытки тренажеров за период по теме"""
        from sqlalchemy.orm import joinedload

        additional_filters = [TrainerAttempt.trainer.has(topic_id=topic_id)]

        join_options = [joinedload(TrainerAttempt.trainer)]

        return RepositoryHelpers.get_completed_attempts_by_period(
            session=self._session,
            model_class=TrainerAttempt,
            student_guid=student_guid,
            start_date=start_date,
            end_date=end_date,
            additional_filters=additional_filters,
            join_options=join_options,
        )

    def get_attempt_statistic(self, attempt_id: int) -> dict:
        """Получить детальную статистику попытки тренажера"""
        attempt = self._session.get(TrainerAttempt, attempt_id)

        if not attempt:
            raise TrainerAttemptNotExist(f"Trainer attempt {attempt_id} not found")

        return AttemptStatisticCalculator.calculate_trainer_statistic(
            attempt=attempt,
        )

    def get_best_attempt_for_trainer(self, user_id: str, trainer_id: int):
        """Получить лучшую попытку пользователя для тренажёра"""
        from quiz.models.trainer import TrainerAttempt

        attempts = (
            self._session.query(TrainerAttempt)
            .filter(
                TrainerAttempt.student_guid == user_id,
                TrainerAttempt.trainer_id == trainer_id,
                TrainerAttempt.status == Status.completed,
            )
            .all()
        )

        if not attempts:
            return None

        # Находим попытку с максимальным процентом правильных ответов
        best_attempt = None
        best_percentage = -1

        for attempt in attempts:
            statistics = self.get_attempt_statistic(attempt.id)
            if not statistics:
                continue

            correct = statistics.get("correct_answers", 0)
            total = statistics.get("total_questions", 0)

            if total > 0:
                percentage = correct / total
                if percentage > best_percentage:
                    best_percentage = percentage
                    best_attempt = attempt

        return best_attempt

    def get_attempt_count(self, user_id: str, trainer_id: int) -> int:
        """Получить количество попыток пользователя для тренажёра"""
        return RepositoryHelpers.get_attempt_count(
            session=self._session,
            model_class=TrainerAttempt,
            user_id=user_id,
            filter_field="trainer_id",
            filter_value=trainer_id,
        )

    def get_user_total_attempts(self, user_id: str) -> int:
        """Получить общее количество попыток пользователя во всех тренажёрах"""
        return RepositoryHelpers.get_user_total_attempts(
            session=self._session,
            model_class=TrainerAttempt,
            user_id=user_id,
        )

    # def get_completed_dates(self, user_id: str) -> Set[date]:
    #     """Получить даты завершённых попыток пользователя"""
    #     from quiz.models.trainer import TrainerAttempt

    #     results = (
    #         self._session.query(func.date(TrainerAttempt.completed_at))
    #         .filter(
    #             TrainerAttempt.student_guid == user_id,
    #             TrainerAttempt.status == Status.completed,
    #             TrainerAttempt.completed_at.isnot(None),
    #         )
    #         .distinct()
    #         .all()
    #     )

    #     return {result[0] for result in results if result[0]}

    def get_user_trainer_attempts(self, user_id: str, trainer_id: int) -> list[Any]:
        """Получить все попытки пользователя для тренажёра"""
        from uuid import UUID

        query = (
            self._session.query(TrainerAttempt)
            .filter(
                TrainerAttempt.student_guid == UUID(user_id),
                TrainerAttempt.trainer_id == trainer_id,
            )
            .order_by(TrainerAttempt.started_at.desc())
        )
        return query.all()

    def get_all_completed_attempts(self, student_id: UUID) -> list[TrainerAttempt]:
        """Получить все завершенные попытки тренажеров за все время"""
        logger.info("Getting all completed trainer attempts for student %s", student_id)

        return (
            self._session.query(TrainerAttempt)
            .options(
                joinedload(TrainerAttempt.trainer),
                joinedload(TrainerAttempt.questions)
                .joinedload(TrainerAttemptQuestion.question)
                .joinedload(Question.variants),
                joinedload(TrainerAttempt.questions).joinedload(TrainerAttemptQuestion.answers),
            )
            .filter(
                TrainerAttempt.student_guid == student_id,
                TrainerAttempt.status == Status.completed,
            )
            .all()
        )

    def get_question_times_by_period(
        self,
        student_guid: UUID,
        topic_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[float]:
        """Получить времена на вопросы для расчета медианы"""
        return RepositoryHelpers.get_question_times_by_period(
            session=self._session,
            attempt_model_class=TrainerAttempt,
            question_model_class=TrainerAttemptQuestion,
            join_conditions={
                "trainer_attempt_id": TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
                "trainer": Trainer.id == TrainerAttempt.trainer_id,
            },
            student_guid=student_guid,
            start_date=start_date,
            end_date=end_date,
            additional_filters=[
                Trainer.topic_id == topic_id,
            ],
        )

    # def get_questions_with_times(self, attempt_id: int) -> list:
    #     """Получить вопросы с временами для попытки"""
    #     attempt = (
    #         self._session.query(TrainerAttempt)
    #         .options(joinedload(TrainerAttempt.questions))
    #         .filter(TrainerAttempt.id == attempt_id)
    #         .first()
    #     )

    #     if not attempt:
    #         return []

    #     logger.info(
    #         "Found %s questions for attempt %s", len(attempt.questions), attempt_id
    #     )
    #     for q in attempt.questions:
    #         logger.info("   Question ID: %s, spend_time: %s", q.id, q.spend_time)

    #     return attempt.questions

    def get_overall_subject_progress(self, student_id: UUID) -> dict[int, dict[str, Any]]:
        """Получить общий прогресс по предметам для тренажеров"""
        logger.info("Getting overall trainer subject progress for student %s", student_id)

        answers_query = (
            self._session.query(TrainerAttemptAnswer, Variant, Question, Subject)
            .join(Variant, Variant.id == TrainerAttemptAnswer.variant_id)
            .join(Question, Question.id == Variant.question_id)
            .join(Subject, Subject.id == Question.subject_id)
            .join(
                TrainerAttemptQuestion,
                TrainerAttemptQuestion.id == TrainerAttemptAnswer.trainer_attempt_question_id,
            )
            .join(
                TrainerAttempt,
                TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
            )
            .filter(
                TrainerAttempt.student_guid == student_id,
                TrainerAttempt.status == Status.completed,
            )
        )

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

    def get_overall_topic_progress(self, student_id: UUID) -> dict[int, dict[str, Any]]:
        """Получить общий прогресс по темам для тренажеров"""
        logger.info("Getting overall trainer topic progress for student %s", student_id)

        answers_query = (
            self._session.query(TrainerAttemptAnswer, Variant, Question, Subject, Topic)
            .join(Variant, Variant.id == TrainerAttemptAnswer.variant_id)
            .join(Question, Question.id == Variant.question_id)
            .join(Subject, Subject.id == Question.subject_id)
            .join(Topic, Topic.id == Question.topic_id)
            .join(
                TrainerAttemptQuestion,
                TrainerAttemptQuestion.id == TrainerAttemptAnswer.trainer_attempt_question_id,
            )
            .join(
                TrainerAttempt,
                TrainerAttempt.id == TrainerAttemptQuestion.trainer_attempt_id,
            )
            .filter(
                TrainerAttempt.student_guid == student_id,
                TrainerAttempt.status == Status.completed,
            )
        )

        answers = answers_query.all()

        topic_stats = {}
        for _answer, variant, _question, subject, topic in answers:
            topic_id = topic.id
            if topic_id not in topic_stats:
                topic_stats[topic_id] = {
                    "topic_id": topic_id,
                    "topic_name": topic.name,
                    "subject_id": subject.id,
                    "subject_name": subject.name,
                    "total_questions": 0,
                    "correct_answers": 0,
                }

            topic_stats[topic_id]["total_questions"] += 1
            if variant.is_correct:
                topic_stats[topic_id]["correct_answers"] += 1

        return topic_stats

    def get_all_completed_attempts_by_period(
        self,
        student_guid: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[TrainerAttempt]:
        """Получить все завершенные попытки тренажеров за период (без фильтрации по теме)"""
        logger.info(
            "Getting all completed trainer attempts for student %s from %s to %s",
            student_guid,
            start_date,
            end_date,
        )

        from sqlalchemy.orm import joinedload

        query = (
            self._session.query(TrainerAttempt)
            .options(
                joinedload(TrainerAttempt.trainer),
                joinedload(TrainerAttempt.questions)
                .joinedload(TrainerAttemptQuestion.question)
                .joinedload(Question.variants),
                joinedload(TrainerAttempt.questions).joinedload(TrainerAttemptQuestion.answers),
            )
            .filter(
                TrainerAttempt.student_guid == student_guid,
                TrainerAttempt.status == Status.completed,
                TrainerAttempt.completed_at >= start_date,
                TrainerAttempt.completed_at <= end_date,
            )
        )

        attempts = query.all()
        logger.info("Found %s completed trainer attempts for period", len(attempts))
        return attempts

    # def get_completed_trainers_in_range(
    #     self, student_guid: UUID, start_utc: datetime, end_utc: datetime
    # ) -> list[TrainerAttempt]:
    #     return (
    #         self._session.query(TrainerAttempt)
    #         .filter(
    #             TrainerAttempt.student_guid == student_guid,
    #             TrainerAttempt.status == Status.completed,
    #             TrainerAttempt.completed_at >= start_utc,
    #             TrainerAttempt.completed_at <= end_utc,
    #         )
    #         .all()
    #     )

    def count_completed_trainers_above_threshold(
        self,
        student_guid: UUID,
        start_utc: datetime,
        end_utc: datetime,
        threshold: float,
    ) -> int:
        attempts = (
            self._session.query(TrainerAttempt)
            .filter(
                TrainerAttempt.student_guid == student_guid,
                TrainerAttempt.status == Status.completed,
                TrainerAttempt.completed_at >= start_utc,
                TrainerAttempt.completed_at <= end_utc,
            )
            .all()
        )
        count = 0
        for attempt in attempts:
            stats = self.get_attempt_statistic(attempt.id)
            total = stats.get("total_questions", 0)
            correct = stats.get("correct", 0)
            if total > 0 and (correct / total * 100) > threshold:
                count += 1
        return count

    def get_trainer_attempts_for_feed(
        self, student_guid: UUID, limit: int, offset: int
    ) -> tuple[list[TrainerAttempt], int]:
        query = (
            self._session.query(TrainerAttempt)
            .filter(
                TrainerAttempt.student_guid == student_guid,
                TrainerAttempt.status == Status.completed,
            )
            .order_by(TrainerAttempt.completed_at.desc())
        )
        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total
