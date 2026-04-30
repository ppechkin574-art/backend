import logging
import random
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from quiz.converters import to_service_question
from quiz.dtos.daily_tests import (
    DailyTestAnswerRequestDTO,
    DailyTestAttemptCreateRepositoryDTO,
    DailyTestAttemptDetailDTO,
    DailyTestAttemptDTO,
    DailyTestDeviceTokenDTO,
    DailyTestHistoryItemDTO,
    DailyTestResultDTO,
    QuestionWithAnswerDetailDTO,
    RegisterDailyTestDeviceTokenDTO,
    SubjectPreferenceDTO,
    SubjectPreferencesResponseDTO,
    UpdateSubjectPreferencesDTO,
    VariantWithAnswerDetailDTO,
)
from quiz.exceptions import AlreadyAnswered, TrainerAttemptNotExist
from quiz.services.cashback import CashbackService
from quiz.uows.uows import UnitOfWorkTests
from quiz.utils.init import (
    AnswerCalculator,
    ProgressRecorder,
    QuestionPreparer,
    VariantValidator,
)
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class DailyTestService:
    """Сервис для работы с ежедневными тестами"""

    MIN_QUESTIONS = 5
    MAX_QUESTIONS = 7
    SUBJECT_TEST_QUESTION_COUNT = 5
    MAX_SUBJECTS = 5
    ASTANA_TIMEZONE_OFFSET_HOURS = 5  # GMT+5

    def __init__(
        self,
        uow: UnitOfWorkTests,
        cache_service: CacheService,
        cashback_service: CashbackService,
    ):
        self._uow = uow
        self._cache_service = cache_service
        self._cashback_service = cashback_service

    @staticmethod
    def _get_astana_today() -> date:
        """Получить текущую дату по времени Астаны (GMT+5)"""
        now_utc = datetime.now(UTC)
        astana_now = now_utc + timedelta(hours=DailyTestService.ASTANA_TIMEZONE_OFFSET_HOURS)
        return astana_now.date()

    @cached(
        strategy=CacheStrategy.USER,
        ttl=604800,
        resource="daily_test_subject_preferences",
    )
    def get_subject_preferences(self, student_guid: UUID) -> SubjectPreferencesResponseDTO:
        """Получить выбранные предметы для ежедневных тестов"""
        with self._uow:
            preferences = self._uow.daily_tests.get_subject_preferences(student_guid)

            subject_dtos = [
                SubjectPreferenceDTO(
                    subject_id=pref.subject.id,
                    subject_name=pref.subject.name,
                    image=(f"https://lumi-unt.kz/uploads{pref.subject.image}" if pref.subject.image else None),
                    is_default=pref.is_default,
                )
                for pref in preferences
            ]

            can_add_more = len(preferences) < self.MAX_SUBJECTS

            return SubjectPreferencesResponseDTO(subjects=subject_dtos, can_add_more=can_add_more)

    def update_subject_preferences(
        self, student_guid: UUID, data: UpdateSubjectPreferencesDTO
    ) -> SubjectPreferencesResponseDTO:
        """Обновить выбранные предметы"""
        with self._uow:
            self._uow.daily_tests.set_subject_preferences(student_guid, data.subject_ids)

            # Сразу получаем обновленные предпочтения
            preferences = self._uow.daily_tests.get_subject_preferences(student_guid)

            subject_dtos = [
                SubjectPreferenceDTO(
                    subject_id=pref.subject.id,
                    subject_name=pref.subject.name,
                    image=(f"https://lumi-unt.kz/uploads{pref.subject.image}" if pref.subject.image else None),
                    is_default=pref.is_default,
                )
                for pref in preferences
            ]

            can_add_more = len(preferences) < self.MAX_SUBJECTS

            self._cache_service.invalidate_by_resource("daily_test_subject_preferences", user_id=student_guid)
            logger.info("Invalidated daily test preferences cache for user %s", student_guid)

            return SubjectPreferencesResponseDTO(subjects=subject_dtos, can_add_more=can_add_more)

    def get_today_test(self, student_guid: UUID, subject_id: int | None = None) -> DailyTestAttemptDTO:
        """Получить тест на сегодня (создать если не существует)"""
        today = self._get_astana_today()

        with self._uow:
            if subject_id is not None:
                # Проверяем, что предмет существует
                subject = self._uow.daily_tests.get_subject_by_id(subject_id)
                if not subject:
                    raise ValueError(f"Предмет с ID {subject_id} не найден")

            # Проверяем, есть ли активная попытка на сегодня
            existing_attempt = self._uow.daily_tests.get_active_attempt_for_today(student_guid, today, subject_id)

            if existing_attempt:
                logger.info(
                    "Found existing daily test attempt %s for today",
                    existing_attempt.id,
                )
                return self._build_attempt_dto(existing_attempt)

            logger.info("Creating new daily test for student %s on %s", student_guid, today)

            if subject_id:
                self._ensure_subject_selected(student_guid, subject_id)
                questions = self._generate_subject_questions(subject_id)
            else:
                # Получаем выбранные предметы
                preferences = self._uow.daily_tests.get_subject_preferences(student_guid)
                if not preferences:
                    raise ValueError(
                        "Не выбраны предметы для ежедневных тестов. Пожалуйста, сначала выберите предметы."
                    )

                subject_ids = [pref.subject_id for pref in preferences]
                questions = self._generate_daily_questions(subject_ids)

            if len(questions) < self.MIN_QUESTIONS:
                raise ValueError(f"Недостаточно вопросов для создания теста. Требуется минимум {self.MIN_QUESTIONS}")

            # Создаем попытку
            attempt_data = DailyTestAttemptCreateRepositoryDTO(
                student_guid=student_guid,
                test_date=today,
                status="in_progress",
                subject_id=subject_id,
            )
            attempt = self._uow.daily_tests.create_attempt(attempt_data)

            # Добавляем вопросы
            question_ids = [q.id for q in questions]
            self._uow.daily_tests.add_questions_to_attempt(attempt.id, question_ids)
            self._uow.commit()  # Коммитим создание попытки

            # Получаем полную попытку
            full_attempt = self._uow.daily_tests.get_attempt_by_id(attempt.id, student_guid)

            return self._build_attempt_dto(full_attempt)

    def submit_answers(self, student_guid: UUID, data: DailyTestAnswerRequestDTO) -> DailyTestResultDTO:
        """Отправить ответы на ежедневный тест"""
        with self._uow:
            # Получаем попытку
            attempt = self._uow.daily_tests.get_attempt_by_id(data.attempt_id, student_guid)

            if not attempt:
                raise TrainerAttemptNotExist(f"Daily test attempt {data.attempt_id} not found")

            # Используем AttemptValidator
            if attempt.status != "in_progress":
                raise AlreadyAnswered(f"Daily test attempt {data.attempt_id} is already completed")

            # Получаем вопросы
            questions = self._uow.daily_tests.get_attempt_questions(attempt.id)

            # Создаем мапу вопросов для быстрой проверки
            questions_map = {q.id: q for q in questions}
            valid_question_ids = set(questions_map.keys())

            # Создаем мапу ответов пользователя
            user_answers_map = {}
            for answer_data in data.questions:
                question_id = answer_data.question_id

                # Проверяем, что question_id принадлежит этой попытке
                if question_id not in valid_question_ids:
                    from quiz.exceptions import QuestionNotFound

                    raise QuestionNotFound(
                        f"Question {question_id} does not belong to attempt {attempt.id}. "
                        f"Valid questions: {list(valid_question_ids)}"
                    )

                variant_ids = answer_data.variants or []
                user_answers_map[question_id] = variant_ids

            # Обработка ответов
            correct_count = 0
            incorrect_count = 0
            skipped_count = 0

            for question in questions:
                user_variant_ids = user_answers_map.get(question.id, [])

                if not user_variant_ids:
                    # Пропущен
                    skipped_count += 1
                    self._uow.daily_tests.save_answer(attempt.id, question.id, None)
                else:
                    # Используем VariantValidator
                    valid_variant_ids = VariantValidator.get_valid_variant_ids(question)
                    VariantValidator.validate_variants_belong_to_question(
                        question_id=question.id,
                        variant_ids=user_variant_ids,
                        valid_variant_ids=valid_variant_ids,
                    )

                    # Сохраняем ответы
                    for variant_id in user_variant_ids:
                        self._uow.daily_tests.save_answer(attempt.id, question.id, variant_id)

                    from quiz.dtos.questions import QuestionRepositoryDTO

                    question_repo = QuestionRepositoryDTO.custom(question)

                    correct_variant_ids = {v.id for v in question.variants if v.is_correct}
                    is_correct, _ = AnswerCalculator.calculate_correctness(
                        question_type=question_repo.type.value,
                        chosen_variant_ids=set(user_variant_ids),
                        correct_variant_ids=correct_variant_ids,
                    )

                    ProgressRecorder.record_attempt_progress(
                        uow=self._uow,
                        user_id=student_guid,
                        question_id=question.id,
                        is_correct=is_correct,
                        attempt_type="daily_test",
                        attempt_id=attempt.id,
                    )

                    if is_correct:
                        correct_count += 1
                    else:
                        incorrect_count += 1

            total_questions = len(questions)
            score = int(correct_count / total_questions * 100) if total_questions > 0 else 0

            self._uow.daily_tests.complete_attempt(attempt, score, correct_count, incorrect_count, skipped_count)

            attempt_id = attempt.id
            test_date = attempt.test_date
            subject_id = attempt.subject_id
            subject_name = attempt.subject.name if attempt.subject else None
            completed_at = attempt.completed_at

            self._uow.commit()

            percentage = (correct_count / total_questions * 100) if total_questions > 0 else 0

            self._cashback_service.check_and_update(student_guid)

            self._invalidate_daily_test_cache(student_guid, data.attempt_id)

            return DailyTestResultDTO(
                attempt_id=attempt_id,
                test_date=test_date,
                score=score,
                correct_answers=correct_count,
                incorrect_answers=incorrect_count,
                skipped_answers=skipped_count,
                total_questions=total_questions,
                percentage=round(percentage, 2),
                completed_at=completed_at,
                subject_id=subject_id,
                subject_name=subject_name,
            )

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="daily_test_history")
    def get_attempts_history(self, student_guid: UUID, limit: int | None = None) -> list[DailyTestHistoryItemDTO]:
        """Получить историю попыток"""
        with self._uow:
            attempts = self._uow.daily_tests.get_attempts_history(student_guid, limit)
            history = self._build_history_items(attempts)
            logger.info(
                "Found %s daily test attempts for student %s",
                len(history),
                student_guid,
            )
            return history

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="daily_test_today_attempts")
    def get_today_attempts(self, student_guid: UUID) -> list[DailyTestHistoryItemDTO]:
        """Получить все попытки за текущую дату по времени Астаны (GMT+5)"""
        with self._uow:
            target_date = self._get_astana_today()

            attempts = self._uow.daily_tests.get_attempts_by_date(student_guid, target_date)
            history = self._build_history_items(attempts)

            logger.info("Found %s daily test attempts for %s on %s (GMT+5)"), len(history), student_guid, target_date
            return history

    @cached(strategy=CacheStrategy.USER, ttl=604800, resource="daily_test_attempt_detail")
    def get_attempt_detail(self, attempt_id: int, student_guid: UUID) -> DailyTestAttemptDetailDTO:
        """Получить детальную информацию о попытке"""
        with self._uow:
            attempt = self._uow.daily_tests.get_attempt_with_details(attempt_id, student_guid)

            if not attempt:
                raise TrainerAttemptNotExist(f"Daily test attempt {attempt_id} not found")

            # Используем AttemptValidator
            if attempt.status == "in_progress":
                raise AlreadyAnswered(
                    f"Cannot view detailed statistics for attempt {attempt_id} - test is still in progress. "
                    f"Please complete the test first."
                )

            # Получаем вопросы
            questions = self._uow.daily_tests.get_attempt_questions(attempt.id)

            # Получаем ответы пользователя
            user_answers = self._uow.daily_tests.get_attempt_answers(attempt.id)

            # Создаем мапу ответов
            user_answers_map = {}
            for answer in user_answers:
                if answer.variant_id:
                    if answer.question_id not in user_answers_map:
                        user_answers_map[answer.question_id] = []
                    user_answers_map[answer.question_id].append(answer.variant_id)

            # Используем QuestionPreparer для подготовки вопросов
            question_details = []
            for idx, question in enumerate(questions):
                user_variant_ids = user_answers_map.get(question.id, [])

                # Используем QuestionPreparer
                prepared_question = QuestionPreparer.prepare_question_with_answers(
                    question_obj=question,
                    user_variant_ids=user_variant_ids,
                    question_number=idx + 1,
                    include_hint=True,
                )

                # Создаем DTO вариантов
                variants = []
                for v in prepared_question["variants"]:
                    variants.append(
                        VariantWithAnswerDetailDTO(
                            id=v["id"],
                            blocks=v["blocks"],
                            is_correct=v["is_correct"],
                            weight=v["weight"],
                            user_selected=v["user_selected"],
                        )
                    )

                question_details.append(
                    QuestionWithAnswerDetailDTO(
                        id=prepared_question["id"],
                        guid=prepared_question["guid"],
                        topic_id=prepared_question["topic_id"],
                        topic_name=prepared_question["topic_name"],
                        subject_id=prepared_question["subject_id"] or 0,
                        subject_name=prepared_question["subject_name"]
                        or (question.subject.name if question.subject else "Unknown"),
                        difficulty=prepared_question["difficulty"],
                        type=prepared_question["type"],
                        blocks=prepared_question["blocks"],
                        hint=prepared_question["hint"],
                        variants=variants,
                        question_number=prepared_question["question_number"],
                        is_correct=prepared_question["is_correct"],
                    )
                )

            total_questions = len(questions)
            percentage = (attempt.correct_answers / total_questions * 100) if total_questions > 0 else 0

            return DailyTestAttemptDetailDTO(
                id=attempt.id,
                guid=attempt.guid,
                test_date=attempt.test_date,
                status=attempt.status,
                score=attempt.score,
                correct_answers=attempt.correct_answers,
                incorrect_answers=attempt.incorrect_answers,
                skipped_answers=attempt.skipped_answers,
                total_questions=total_questions,
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
                percentage=round(percentage, 2),
                subject_id=attempt.subject_id,
                subject_name=(attempt.subject.name if getattr(attempt, "subject", None) else None),
                questions=question_details,
            )

    def register_device_token(
        self, student_guid: UUID, data: RegisterDailyTestDeviceTokenDTO
    ) -> DailyTestDeviceTokenDTO:
        """Сохранить или обновить FCM токен устройства"""
        token = data.token.strip()
        if not token:
            raise ValueError("FCM токен не может быть пустым")

        with self._uow:
            entity = self._uow.daily_tests.upsert_device_token(
                student_guid=student_guid,
                token=token,
                platform=data.platform,
                device_id=data.device_id,
            )

            token_suffix = token[-6:] if len(token) > 6 else token
            logger.info(
                "Daily test device token stored successfully for student %s (platform=%s, suffix=%s)",
                student_guid,
                data.platform,
                token_suffix,
            )

            return DailyTestDeviceTokenDTO(
                id=entity.id,
                student_guid=entity.student_guid,
                token=entity.token,
                platform=entity.platform,
                device_id=entity.device_id,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )

    # Вспомогательные методы
    def _ensure_subject_selected(self, student_guid: UUID, subject_id: int) -> None:
        preferences = self._uow.daily_tests.get_subject_preferences(student_guid)
        if not any(pref.subject_id == subject_id for pref in preferences):
            raise ValueError("Этот предмет не выбран в настройках ежедневных тестов.")

    def _generate_subject_questions(self, subject_id: int) -> list:
        """Сформировать фиксированное количество вопросов по конкретному предмету"""
        questions = self._uow.questions.get_questions_by_subject(subject_id)
        if len(questions) < self.SUBJECT_TEST_QUESTION_COUNT:
            raise ValueError(
                f"Недостаточно вопросов по выбранному предмету (нужно минимум {self.SUBJECT_TEST_QUESTION_COUNT})."
            )
        random.shuffle(questions)
        return questions[: self.SUBJECT_TEST_QUESTION_COUNT]

    def _generate_daily_questions(self, subject_ids: list[int]) -> list:
        """Генерировать случайные вопросы для ежедневного теста"""
        all_questions = []

        # Получаем вопросы по каждому предмету
        for subject_id in subject_ids:
            questions = self._uow.questions.get_questions_by_subject(subject_id)
            all_questions.extend(questions)

        # Перемешиваем
        random.shuffle(all_questions)

        # Берем случайное количество от MIN_QUESTIONS до MAX_QUESTIONS
        question_count = random.randint(self.MIN_QUESTIONS, self.MAX_QUESTIONS)  # noqa S311
        selected_questions = all_questions[: min(question_count, len(all_questions))]

        logger.info(
            "Generated %s questions from %s available for subjects %s",
            len(selected_questions),
            len(all_questions),
            subject_ids,
        )

        return selected_questions

    def _build_attempt_dto(self, attempt) -> DailyTestAttemptDTO:
        """Построить DTO попытки с вопросами"""
        from quiz.dtos.questions import QuestionRepositoryDTO

        questions_db = self._uow.daily_tests.get_attempt_questions(attempt.id)
        # Конвертируем SQLAlchemy объекты в DTOs через существующий конвертер
        questions_repo = [QuestionRepositoryDTO.custom(q) for q in questions_db]
        questions_service = [to_service_question(q) for q in questions_repo]

        return DailyTestAttemptDTO(
            id=attempt.id,
            guid=attempt.guid,
            test_date=attempt.test_date,
            status=attempt.status,
            score=attempt.score,
            correct_answers=attempt.correct_answers,
            incorrect_answers=attempt.incorrect_answers,
            skipped_answers=attempt.skipped_answers,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            total_questions=len(questions_service),
            subject_id=attempt.subject_id,
            subject_name=(attempt.subject.name if getattr(attempt, "subject", None) else None),
            questions=questions_service,
        )

    def _build_history_items(self, attempts: list) -> list[DailyTestHistoryItemDTO]:
        history = []
        for attempt in attempts:
            questions = self._uow.daily_tests.get_attempt_questions(attempt.id)
            total_questions = len(questions)
            history.append(
                DailyTestHistoryItemDTO(
                    id=attempt.id,
                    guid=attempt.guid,
                    test_date=attempt.test_date,
                    subject_id=attempt.subject_id,
                    subject_name=(attempt.subject.name if getattr(attempt, "subject", None) else None),
                    status=attempt.status,
                    score=attempt.score,
                    correct_answers=attempt.correct_answers,
                    incorrect_answers=attempt.incorrect_answers,
                    skipped_answers=attempt.skipped_answers,
                    total_questions=total_questions,
                    completed_at=attempt.completed_at,
                )
            )
        return history

    def _invalidate_daily_test_cache(self, student_guid: UUID, attempt_id: int | None = None):
        """Инвалидировать кеши ежедневных тестов"""
        resources = [
            "daily_test_history",
            "daily_test_today_attempts",
        ]

        if attempt_id:
            resources.append("daily_test_attempt_detail")
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="daily_test_attempt_detail",
                    user_id=student_guid,
                    params=f"id:{attempt_id}",
                )
            )

        deleted = self._cache_service.invalidate_by_resources(resources, user_id=student_guid)
        logger.info(
            "Invalidated daily test cache for user %s, deleted %s keys",
            student_guid,
            deleted,
        )
