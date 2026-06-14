import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from quiz.dtos.daily_tests import DailyTestAttemptCreateRepositoryDTO
from quiz.models.daily_tests import (
    DailyTestAnswer,
    DailyTestAttempt,
    DailyTestAttemptQuestion,
    DailyTestDeviceToken,
    DailyTestSubjectPreference,
)
from quiz.models.edu_content import Question, Subject, Variant
from quiz.models.text_blocks import TextBlockLink
from quiz.utils.init import RepositoryHelpers

logger = logging.getLogger(__name__)


class DailyTestRepository:
    def __init__(self, session: Session):
        self._session = session

    # Subject Preferences методы
    def get_subject_preferences(self, student_guid: UUID) -> list[DailyTestSubjectPreference]:
        """Получить выбранные предметы пользователя"""
        return (
            self._session.query(DailyTestSubjectPreference)
            .options(joinedload(DailyTestSubjectPreference.subject))
            .filter(DailyTestSubjectPreference.student_guid == student_guid)
            .all()
        )

    def set_subject_preferences(self, student_guid: UUID, subject_ids: list[int]) -> None:
        """Установить выбранные предметы пользователя"""
        # Удаляем старые предпочтения
        self._session.query(DailyTestSubjectPreference).filter(
            DailyTestSubjectPreference.student_guid == student_guid
        ).delete()

        # Создаем новые
        for subject_id in subject_ids:
            preference = DailyTestSubjectPreference(
                student_guid=student_guid,
                subject_id=subject_id,
                is_default=False,
            )
            self._session.add(preference)

        # Flush чтобы новые записи были видны при следующем запросе
        self._session.flush()

        logger.info("Set subject preferences for student %s: %s", student_guid, subject_ids)

    # def get_subject_by_name(self, name: str) -> Subject | None:
    #     """Найти предмет по названию (без учета регистра)"""
    #     return self._session.query(Subject).filter(func.lower(Subject.name) == func.lower(name.strip())).first()

    def get_subject_by_id(self, subject_id: int) -> Subject | None:
        """Найти предмет по ID"""
        return self._session.query(Subject).filter(Subject.id == subject_id).first()

    # Attempt методы
    def get_active_attempt_for_today(
        self, student_guid: UUID, test_date: date, subject_id: int | None = None
    ) -> DailyTestAttempt | None:
        """Получить активную попытку на сегодня"""
        query = (
            self._session.query(DailyTestAttempt)
            .options(joinedload(DailyTestAttempt.subject))
            .filter(
                DailyTestAttempt.student_guid == student_guid,
                DailyTestAttempt.test_date == test_date,
                DailyTestAttempt.status == "in_progress",
            )
        )

        if subject_id is None:
            query = query.filter(DailyTestAttempt.subject_id.is_(None))
        else:
            query = query.filter(DailyTestAttempt.subject_id == subject_id)

        return query.first()

    def create_attempt(self, attempt_data: DailyTestAttemptCreateRepositoryDTO) -> DailyTestAttempt:
        """Создать новую попытку"""
        attempt = DailyTestAttempt(
            student_guid=attempt_data.student_guid,
            test_date=attempt_data.test_date,
            status=attempt_data.status,
            subject_id=attempt_data.subject_id,
        )
        self._session.add(attempt)
        self._session.flush()
        self._session.refresh(attempt)

        logger.info(
            "Created daily test attempt %s for student %s",
            attempt.id,
            attempt_data.student_guid,
        )
        return attempt

    def add_questions_to_attempt(self, attempt_id: int, question_ids: list[int]) -> None:
        """Добавить вопросы к попытке"""
        for idx, question_id in enumerate(question_ids):
            attempt_question = DailyTestAttemptQuestion(
                daily_test_attempt_id=attempt_id,
                question_id=question_id,
                order_number=idx + 1,
            )
            self._session.add(attempt_question)

        logger.info("Added %s questions to attempt %s", len(question_ids), attempt_id)

    def get_attempt_by_id(self, attempt_id: int, student_guid: UUID) -> DailyTestAttempt | None:
        """Получить попытку по ID"""
        return (
            self._session.query(DailyTestAttempt)
            .options(joinedload(DailyTestAttempt.subject))
            .filter(
                and_(
                    DailyTestAttempt.id == attempt_id,
                    DailyTestAttempt.student_guid == student_guid,
                )
            )
            .first()
        )

    def get_attempt_questions(self, attempt_id: int) -> list[Question]:
        """Получить вопросы попытки"""
        attempt_questions = (
            self._session.query(DailyTestAttemptQuestion)
            .options(
                joinedload(DailyTestAttemptQuestion.question).joinedload(Question.subject),
                joinedload(DailyTestAttemptQuestion.question).joinedload(Question.topic),
                joinedload(DailyTestAttemptQuestion.question)
                .joinedload(Question.variants)
                .joinedload(Variant.link)
                .joinedload(TextBlockLink.blocks),
            )
            .filter(DailyTestAttemptQuestion.daily_test_attempt_id == attempt_id)
            .order_by(DailyTestAttemptQuestion.order_number)
            .all()
        )

        return [aq.question for aq in attempt_questions]

    def save_answer(self, attempt_id: int, question_id: int, variant_id: int | None) -> None:
        """Сохранить ответ пользователя"""
        answer = DailyTestAnswer(
            daily_test_attempt_id=attempt_id,
            question_id=question_id,
            variant_id=variant_id,
        )
        self._session.add(answer)
        self._session.flush()

    def get_attempt_answers(self, attempt_id: int) -> list[DailyTestAnswer]:
        """Получить все ответы попытки"""
        return (
            self._session.query(DailyTestAnswer)
            .options(
                joinedload(DailyTestAnswer.variant).joinedload(Variant.question),
                joinedload(DailyTestAnswer.question),
            )
            .filter(DailyTestAnswer.daily_test_attempt_id == attempt_id)
            .all()
        )

    def complete_attempt(
        self,
        attempt: DailyTestAttempt,
        score: int,
        correct: int,
        incorrect: int,
        skipped: int,
    ) -> None:
        """Завершить попытку"""
        attempt.status = "completed"
        attempt.score = score
        attempt.correct_answers = correct
        attempt.incorrect_answers = incorrect
        attempt.skipped_answers = skipped
        attempt.completed_at = datetime.now(UTC)
        self._session.add(attempt)

        logger.info(
            "Completed daily test attempt %s: score=%s, correct=%s, incorrect=%s, skipped=%s",
            attempt.id,
            score,
            correct,
            incorrect,
            skipped,
        )

    def get_attempts_history(self, student_guid: UUID, limit: int | None = None) -> list[DailyTestAttempt]:
        """Получить историю попыток"""
        query = (
            self._session.query(DailyTestAttempt)
            .options(joinedload(DailyTestAttempt.subject))
            .filter(DailyTestAttempt.student_guid == student_guid)
            .order_by(DailyTestAttempt.test_date.desc())
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_attempts_by_date(self, student_guid: UUID, target_date: date) -> list[DailyTestAttempt]:
        """Получить попытки за конкретную дату"""
        return (
            self._session.query(DailyTestAttempt)
            .options(joinedload(DailyTestAttempt.subject))
            .filter(
                DailyTestAttempt.student_guid == student_guid,
                DailyTestAttempt.test_date == target_date,
            )
            .order_by(DailyTestAttempt.started_at.asc())
            .all()
        )

    def get_attempt_with_details(self, attempt_id: int, student_guid: UUID) -> DailyTestAttempt | None:
        """Получить попытку с деталями"""
        return (
            self._session.query(DailyTestAttempt)
            .options(
                joinedload(DailyTestAttempt.subject),
                joinedload(DailyTestAttempt.questions)
                .joinedload(DailyTestAttemptQuestion.question)
                .joinedload(Question.variants)
                .joinedload(Variant.link)
                .joinedload(TextBlockLink.blocks),
                joinedload(DailyTestAttempt.answers),
            )
            .filter(
                and_(
                    DailyTestAttempt.id == attempt_id,
                    DailyTestAttempt.student_guid == student_guid,
                )
            )
            .first()
        )

    # Device token methods
    def upsert_device_token(
        self,
        student_guid: UUID,
        token: str,
        platform: str | None = None,
        device_id: str | None = None,
    ) -> DailyTestDeviceToken:
        """Сохранить или обновить токен устройства для уведомлений"""
        sanitized_token = token.strip()
        existing = (
            self._session.query(DailyTestDeviceToken)
            .filter(DailyTestDeviceToken.token == sanitized_token)
            .one_or_none()
        )

        if existing:
            existing.student_guid = student_guid
            existing.platform = platform
            existing.device_id = device_id
            existing.updated_at = datetime.now(UTC)
            entity = existing
        else:
            entity = DailyTestDeviceToken(
                student_guid=student_guid,
                token=sanitized_token,
                platform=platform,
                device_id=device_id,
            )
            self._session.add(entity)

        self._session.flush()
        self._session.refresh(entity)

        token_suffix = sanitized_token[-6:] if len(sanitized_token) > 6 else sanitized_token
        logger.info(
            "Stored daily test device token for student %s (platform=%s, suffix=%s)",
            student_guid,
            platform,
            token_suffix,
        )
        return entity

    def fetch_device_tokens(
        self,
        *,
        last_id: int | None = None,
        limit: int = 1000,
    ) -> list[DailyTestDeviceToken]:
        """Получить пачку токенов, упорядоченную по ID."""
        query = self._session.query(DailyTestDeviceToken).order_by(DailyTestDeviceToken.id.asc())
        if last_id is not None:
            query = query.filter(DailyTestDeviceToken.id > last_id)
        return query.limit(limit).all()

    def delete_tokens(self, tokens: list[str]) -> int:
        """Удалить токены (например, если Firebase вернул ошибку UNREGISTERED)."""
        if not tokens:
            return 0
        deleted = (
            self._session.query(DailyTestDeviceToken)
            .filter(DailyTestDeviceToken.token.in_(tokens))
            .delete(synchronize_session=False)
        )
        logger.info("Removed %s invalid FCM tokens", deleted)
        return deleted

    def get_completed_attempts_by_period(
        self, student_guid: UUID, start_date: datetime, end_date: datetime
    ) -> list[DailyTestAttempt]:
        """Получить завершенные попытки daily тестов за период"""
        from sqlalchemy.orm import joinedload

        additional_filters = []
        join_options = [
            joinedload(DailyTestAttempt.subject),
            joinedload(DailyTestAttempt.questions),
            joinedload(DailyTestAttempt.answers),
        ]

        return RepositoryHelpers.get_completed_attempts_by_period(
            session=self._session,
            model_class=DailyTestAttempt,
            student_guid=student_guid,
            start_date=start_date,
            end_date=end_date,
            status_field_name="status",
            completed_status="completed",
            additional_filters=additional_filters,
            join_options=join_options,
        )

    # def get_daily_test_statistic(self, attempt_id: int) -> dict[str, Any]:
    #     """Получить статистику попытки daily теста"""
    #     attempt = self._session.get(DailyTestAttempt, attempt_id)

    #     if not attempt:
    #         return AttemptStatisticCalculator.get_empty_statistic()

    #     return AttemptStatisticCalculator.calculate_daily_test_statistic(attempt=attempt)

    def get_all_completed_attempts(self, student_id: UUID) -> list[DailyTestAttempt]:
        """Получить все завершенные попытки daily тестов за все время"""
        logger.info("Getting all completed daily attempts for student %s", student_id)

        return (
            self._session.query(DailyTestAttempt)
            .options(
                joinedload(DailyTestAttempt.subject),
                joinedload(DailyTestAttempt.questions),
                joinedload(DailyTestAttempt.answers),
            )
            .filter(
                DailyTestAttempt.student_guid == student_id,
                DailyTestAttempt.status == "completed",
            )
            .all()
        )

    def get_overall_subject_progress(self, student_id: UUID) -> dict[int, dict[str, Any]]:
        """Получить общий прогресс по предметам для daily тестов"""
        logger.info("Getting overall daily subject progress for student %s", student_id)

        attempts = self.get_all_completed_attempts(student_id)

        subject_stats = {}
        for attempt in attempts:
            if attempt.subject_id:
                subject_id = attempt.subject_id
                subject_name = getattr(attempt.subject, "name", f"Subject {subject_id}")

                if subject_id not in subject_stats:
                    subject_stats[subject_id] = {
                        "subject_id": subject_id,
                        "subject_name": subject_name,
                        "total_questions": 0,
                        "correct_answers": 0,
                    }

                attempt_total = attempt.correct_answers + attempt.incorrect_answers + attempt.skipped_answers
                subject_stats[subject_id]["total_questions"] += attempt_total
                subject_stats[subject_id]["correct_answers"] += attempt.correct_answers
            else:
                try:
                    questions = self.get_attempt_questions(attempt.id)
                    answers = self.get_attempt_answers(attempt.id)

                    answers_dict = {}
                    for answer in answers:
                        if answer.question_id not in answers_dict:
                            answers_dict[answer.question_id] = []
                        if answer.variant_id:
                            answers_dict[answer.question_id].append(answer.variant_id)

                    for question in questions:
                        subject_id = question.subject_id
                        subject_name = question.subject.name if question.subject else f"Subject {subject_id}"

                        if subject_id not in subject_stats:
                            subject_stats[subject_id] = {
                                "subject_id": subject_id,
                                "subject_name": subject_name,
                                "total_questions": 0,
                                "correct_answers": 0,
                            }

                        subject_stats[subject_id]["total_questions"] += 1

                        user_variant_ids = answers_dict.get(question.id, [])
                        if user_variant_ids:
                            correct_variant_ids = {v.id for v in question.variants if v.is_correct}
                            is_correct = set(user_variant_ids) == correct_variant_ids

                            if is_correct:
                                subject_stats[subject_id]["correct_answers"] += 1
                except Exception as e:
                    logger.warning("Error processing daily attempt %s: %s", attempt.id, e)
                    continue

        return subject_stats

    # def get_completed_attempt_in_range(
    #     self, student_guid: UUID, start_utc: datetime, end_utc: datetime
    # ) -> DailyTestAttempt | None:
    #     return (
    #         self._session.query(DailyTestAttempt)
    #         .filter(
    #             DailyTestAttempt.student_guid == student_guid,
    #             DailyTestAttempt.status == "completed",
    #             DailyTestAttempt.completed_at >= start_utc,
    #             DailyTestAttempt.completed_at <= end_utc,
    #         )
    #         .first()
    #     )

    # def has_completed_daily_test_in_range(
    #     self, student_guid: UUID, start_utc: datetime, end_utc: datetime
    # ) -> bool:
    #     return (
    #         self._session.query(DailyTestAttempt)
    #         .filter(
    #             DailyTestAttempt.student_guid == student_guid,
    #             DailyTestAttempt.status == "completed",
    #             DailyTestAttempt.completed_at >= start_utc,
    #             DailyTestAttempt.completed_at <= end_utc,
    #         )
    #         .first()
    #         is not None
    #     )

    def get_daily_test_attempts_for_feed(
        self, student_guid: UUID, limit: int, offset: int
    ) -> tuple[list[DailyTestAttempt], int]:
        query = (
            self._session.query(DailyTestAttempt)
            .filter(
                DailyTestAttempt.student_guid == student_guid,
                DailyTestAttempt.status == "completed",
            )
            .order_by(DailyTestAttempt.completed_at.desc())
        )
        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total

    def count_completed_daily_tests_in_range(self, student_guid: UUID, start_utc: datetime, end_utc: datetime) -> int:
        return (
            self._session.query(DailyTestAttempt)
            .filter(
                DailyTestAttempt.student_guid == student_guid,
                DailyTestAttempt.status == "completed",
                DailyTestAttempt.completed_at >= start_utc,
                DailyTestAttempt.completed_at <= end_utc,
            )
            .count()
        )
