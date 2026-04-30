import logging

from fastapi import HTTPException
from starlette.status import (
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from quiz.dtos.ent_options import (
    EntOptionCreateServiceDTO,
)
from quiz.dtos.enums import TestType
from quiz.dtos.hint import HintCreateServiceDTO
from quiz.dtos.questions import ImportQuestionCreateDTO, QuestionCreateServiceDTO
from quiz.dtos.variants import VariantCreateServiceDTO
from quiz.parsers.question import QuestionParserXLSX
from quiz.services.ent_options import EntOptionServiceInterface
from quiz.services.ent_questions import (
    EntOptionQuestionServiceInterface,
)
from quiz.services.questions import QuestionServiceInterface
from quiz.services.subjects import SubjectServiceInterface
from quiz.services.topics import TopicServiceInterface
from quiz.services.trainers import TrainerServiceInterface

logger = logging.getLogger(__name__)


class ImportService:
    def __init__(
        self,
        question_service: QuestionServiceInterface,
        ent_option_service: EntOptionServiceInterface,
        ent_question_service: EntOptionQuestionServiceInterface,
        trainer_service: TrainerServiceInterface,
        topic_service: TopicServiceInterface,
        subject_service: SubjectServiceInterface,
        parser: QuestionParserXLSX,
    ):
        self.question_service = question_service
        self.ent_option_service = ent_option_service
        self.ent_question_service = ent_question_service
        self.trainer_service = trainer_service
        self.topic_service = topic_service
        self.subject_service = subject_service
        self.parser = parser

    async def import_questions(self, file, import_type: TestType) -> dict:
        """Основной метод импорта"""
        try:
            if not file.filename.endswith((".xlsx", ".xls")):
                raise ValueError("Only Excel files are allowed")

            class ImportFormData:
                def __init__(self, file, type):
                    self.file = file
                    self.type = type

            form_data = ImportFormData(file=file, type=import_type)
            questions, ent_options, errors, errors_count = self.parser.parse(form_data)

            logger.info("Parser results: %s questions, %s errors", len(questions), errors_count)

            if import_type == TestType.training:
                result = await self._import_training_questions(questions, errors, errors_count)
            else:
                result = await self._import_ent_questions(questions, errors, errors_count)

            if result["errors_count"] > 0:
                raise HTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=result)

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Unexpected error in import_questions: %s", str(e))
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def _import_training_questions(self, questions: list, errors: list[str], errors_count: int) -> dict:
        imported_count = 0
        updated_count = 0
        trainers_processed = set()

        for i, import_question in enumerate(questions, 1):
            try:
                logger.info("Processing question %s/%s", i, len(questions))

                subject = await self.subject_service.get_or_create_by_name(import_question.subject)
                logger.info("Subject ID for '%s': %s", import_question.subject, subject.id)

                topic = await self.topic_service.get_or_create_topic(import_question.topic_name, subject.id)
                logger.info("Topic ID for '%s': %s", import_question.topic_name, topic.id)

                trainer = await self._get_or_create_trainer_for_topic(topic.id, import_question.topic_name)

                existing_question_id = await self._find_existing(
                    import_question, subject.id, topic.id, TestType.training
                )

                if existing_question_id:
                    try:
                        await self.question_service.delete(existing_question_id)
                        logger.info("Deleted old question with ID %s", existing_question_id)

                        created_question = await self._create_question(import_question, subject.id, topic.id)
                        question_id = created_question.id
                        updated_count += 1
                        logger.info(
                            "Created new question with ID %s to replace old one",
                            question_id,
                        )

                    except Exception as e:
                        logger.warning(
                            "Could not delete old question %s: %s",
                            existing_question_id,
                            str(e),
                        )
                        created_question = await self._create_question(import_question, subject.id, topic.id)
                        question_id = created_question.id
                        updated_count += 1
                        logger.info(
                            "Created new question with ID %s (old question not deleted)",
                            question_id,
                        )
                else:
                    created_question = await self._create_question(import_question, subject.id, topic.id)
                    question_id = created_question.id
                    imported_count += 1
                    logger.info("Created new question with ID %s", question_id)

                if not await self._is_question_in_trainer(trainer.id, question_id):
                    await self.trainer_service.add_question_to_trainer(trainer.id, question_id)
                    trainers_processed.add(trainer.id)
                    logger.info("Added question %s to trainer %s", question_id, trainer.id)
                else:
                    logger.info("Question %s already in trainer %s", question_id, trainer.id)

            except Exception as e:
                error_msg = f"Ошибка импорта вопроса {i}: {str(e)}"
                errors.append(error_msg)
                errors_count += 1
                logger.exception(error_msg)

        trainers_updated = len(trainers_processed)

        return self._build_response(
            imported_count=imported_count,
            detected_questions=len(questions),
            errors=errors,
            errors_count=errors_count,
            trainers_updated=trainers_updated,
            updated_count=updated_count,
        )

    async def _get_or_create_trainer_for_topic(self, topic_id: int, topic_name: str):
        """Получает или создаёт тренажёр для темы"""
        try:
            existing_trainers = self.trainer_service.get_trainers_by_topic_id(topic_id)
            if existing_trainers:
                logger.info("Found existing trainer for topic %s", topic_id)
                return existing_trainers[0]

            trainer_name = f"Тренажёр по теме '{topic_name}'"
            trainer = await self.trainer_service.get_or_create_trainer_for_topic(topic_id, trainer_name)
            logger.info("Created new trainer with ID %s", trainer.id)
            return trainer

        except Exception as e:
            logger.exception("Error getting/creating trainer for topic %s: %s", topic_id, str(e))
            raise

    async def _find_existing(
        self, import_question, subject_id: int, context_id: int, import_type: TestType
    ) -> int | None:
        try:
            question_text = self._extract_text(import_question.question_blocks)
            if not question_text:
                return None

            if import_type == TestType.training:
                existing_questions = self.question_service.get_questions_by_topic(context_id)
            else:
                existing_questions = self.question_service.get_questions_by_subject(subject_id)

            for existing_question in existing_questions:
                if not hasattr(existing_question, "blocks") or not hasattr(existing_question, "variants"):
                    logger.warning("Unexpected question type: %s", type(existing_question))
                    continue

                existing_text = self._extract_text(existing_question.blocks)
                if not self._is_similar_text(question_text, existing_text):
                    continue

                if existing_question.difficulty != import_question.difficulty:
                    continue

                if self._compare_variants(existing_question.variants, import_question.answers):
                    return existing_question.id

            return None

        except Exception as e:
            logger.exception("Error finding existing question: %s", str(e))
            return None

    def _is_similar_text(self, text1: str, text2: str, similarity_threshold: float = 0.9) -> bool:
        """Проверяет схожесть текстов"""
        if not text1 or not text2:
            return False

        normalized1 = " ".join(text1.lower().split())
        normalized2 = " ".join(text2.lower().split())

        if normalized1 == normalized2:
            return True

        words1 = set(normalized1.split())
        words2 = set(normalized2.split())

        if not words1 or not words2:
            return False

        common_words = words1.intersection(words2)
        similarity = len(common_words) / max(len(words1), len(words2))

        return similarity >= similarity_threshold

    def _compare_variants(self, existing_variants, new_variants) -> bool:
        """Сравнивает варианты ответов - работает с DTO"""
        if len(existing_variants) != len(new_variants):
            return False

        existing_vars = []
        for variant in existing_variants:
            text = self._extract_text(variant.blocks)
            existing_vars.append(
                {
                    "text": " ".join(text.lower().split()),
                    "is_correct": variant.is_correct,
                }
            )

        new_vars = []
        for variant in new_variants:
            text = self._extract_text(variant.blocks)
            new_vars.append(
                {
                    "text": " ".join(text.lower().split()),
                    "is_correct": variant.is_correct,
                }
            )

        existing_vars.sort(key=lambda x: x["text"])
        new_vars.sort(key=lambda x: x["text"])

        for existing, new in zip(existing_vars, new_vars, strict=False):
            if existing["text"] != new["text"] or existing["is_correct"] != new["is_correct"]:
                return False

        return True

    def _extract_text(self, blocks: list | object) -> str:
        """Универсальный метод извлечения текста из блоков - работает с DTO"""
        if not blocks:
            return ""

        if hasattr(blocks, "blocks"):
            blocks = blocks.blocks

        if not isinstance(blocks, list):
            if hasattr(blocks, "value"):
                return str(blocks.value).strip()
            elif hasattr(blocks, "text"):
                return str(blocks.text).strip()
            else:
                return ""

        text_parts = []
        for block in blocks:
            if hasattr(block, "value"):
                text_parts.append(str(block.value))
            elif hasattr(block, "text"):
                text_parts.append(str(block.text))

        full_text = " ".join(text_parts).strip()
        return " ".join(full_text.split())

    async def _is_question_in_trainer(self, trainer_id: int, question_id: int) -> bool:
        """Проверяет, есть ли вопрос в тренажёре"""
        try:
            trainer_questions = await self.trainer_service.get_questions_by_trainer(trainer_id)
            question_ids = [q.id for q in trainer_questions]
            return question_id in question_ids
        except Exception as e:
            logger.exception("Error checking question in trainer: %s", str(e))
            return False

    async def _create_question(self, import_question, subject_id: int, topic_id: int = None):
        """Универсальный метод создания вопроса"""
        try:
            logger.info(
                "Creating question from import: %s variants",
                len(import_question.answers),
            )

            question_create = QuestionCreateServiceDTO(
                subject_id=subject_id,
                topic_id=topic_id,
                difficulty=import_question.difficulty,
                type=import_question.type,
                blocks=import_question.question_blocks,
                variants=[
                    VariantCreateServiceDTO(
                        blocks=variant.blocks,
                        is_correct=variant.is_correct,
                        weight=variant.weight,
                    )
                    for variant in import_question.answers
                ],
                hint=(
                    HintCreateServiceDTO(blocks=import_question.hint_blocks) if import_question.hint_blocks else None
                ),
            )

            created_question = self.question_service.create(question_create)
            logger.info("Successfully created question with ID %s", created_question.id)

            return created_question

        except Exception as e:
            logger.exception("Error in _create_question: %s", str(e))
            raise

    async def _import_ent_questions(
        self,
        questions: list[ImportQuestionCreateDTO],
        errors: list[str],
        errors_count: int,
    ) -> dict:
        imported_questions_count = 0
        updated_questions_count = 0
        created_ent_options_count = 0
        duplicate_ent_options_count = 0
        skipped_questions_in_ent_count = 0

        ent_questions_map = {}

        for import_question in questions:
            if not import_question.ent_option_number:
                errors.append("Для ЕНТ вопроса не указан номер варианта")
                errors_count += 1
                continue

            option_num = import_question.ent_option_number
            if option_num not in ent_questions_map:
                ent_questions_map[option_num] = []
            ent_questions_map[option_num].append(import_question)

        logger.info("Found %s option groups in file", len(ent_questions_map))

        for file_option_num, question_group in ent_questions_map.items():
            try:
                logger.info(
                    "Processing option group %s with %s questions",
                    file_option_num,
                    len(question_group),
                )

                first_question = question_group[0]
                subject = await self.subject_service.get_or_create_by_name(first_question.subject)

                subjects_in_group = {q.subject for q in question_group}
                if len(subjects_in_group) > 1:
                    error_msg = (
                        f"В варианте {file_option_num} обнаружены разные предметы: {', '.join(subjects_in_group)}"
                    )
                    errors.append(error_msg)
                    errors_count += 1
                    continue

                valid_question_ids = []
                should_create_option = False

                for i, import_question in enumerate(question_group, 1):
                    try:
                        existing_question_id = await self._find_existing(
                            import_question, subject.id, None, TestType.ent
                        )

                        if existing_question_id:
                            logger.info(
                                "Found existing question with ID %s",
                                existing_question_id,
                            )

                            is_in_ent_option = self.ent_question_service.is_question_in_any_ent_option(
                                existing_question_id
                            )

                            if is_in_ent_option:
                                logger.warning(
                                    "Question %s already exists in another ENT option. Skipping this question.",
                                    existing_question_id,
                                )
                                skipped_questions_in_ent_count += 1
                            else:
                                try:
                                    await self.question_service.delete(existing_question_id)
                                    logger.info(
                                        "Deleted old ENT question with ID %s",
                                        existing_question_id,
                                    )

                                    created_question = await self._create_question(import_question, subject.id)
                                    valid_question_ids.append(created_question.id)
                                    updated_questions_count += 1
                                    should_create_option = True
                                    logger.info(
                                        "Created new ENT question with ID %s to replace old one",
                                        created_question.id,
                                    )

                                except Exception as e:
                                    logger.warning(
                                        "Could not delete old ENT question %s: %s",
                                        existing_question_id,
                                        e,
                                    )
                                    created_question = await self._create_question(import_question, subject.id)
                                    valid_question_ids.append(created_question.id)
                                    updated_questions_count += 1
                                    should_create_option = True
                                    logger.info(
                                        "Created new ENT question with ID %s (old question not deleted)",
                                        created_question.id,
                                    )
                        else:
                            created_question = await self._create_question(import_question, subject.id)
                            imported_questions_count += 1
                            valid_question_ids.append(created_question.id)
                            logger.info("Created new question with ID %s", created_question.id)
                            should_create_option = True

                    except Exception as e:
                        error_msg = f"Ошибка импорта вопроса {i} в варианте {file_option_num}: {str(e)}"
                        errors.append(error_msg)
                        errors_count += 1
                        logger.exception(error_msg)

                if not should_create_option or not valid_question_ids:
                    logger.warning(
                        "No valid questions for option %s. Skipping option creation.",
                        file_option_num,
                    )
                    duplicate_ent_options_count += 1
                    continue

                existing_ent_option_id = self.ent_question_service.find_duplicate_ent_option(
                    valid_question_ids, subject.id
                )

                if existing_ent_option_id:
                    logger.info(
                        "ENT option already exists with ID %s. Skipping creation.",
                        existing_ent_option_id,
                    )
                    duplicate_ent_options_count += 1
                    continue

                existing_options_count = self.ent_option_service.get_max_option_number()
                new_option_number = existing_options_count + 1

                created_option = self.ent_option_service.create(
                    EntOptionCreateServiceDTO(option_number=new_option_number, subject_id=subject.id)
                )
                created_ent_options_count += 1
                logger.info(
                    "Created new ENT option with ID %s, number %s",
                    created_option.id,
                    new_option_number,
                )

                for question_id in valid_question_ids:
                    try:
                        self.ent_option_service.add_question_to_ent(created_option.id, question_id)
                        logger.info(
                            "Added question %s to ENT option %s",
                            question_id,
                            created_option.id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to add question %s to ENT option: %s",
                            question_id,
                            e,
                        )

                logger.info(
                    "Option %s: %s valid questions out of %s total",
                    file_option_num,
                    len(valid_question_ids),
                    len(question_group),
                )

            except Exception as e:
                error_msg = f"Ошибка обработки группы вариантов {file_option_num}: {str(e)}"
                errors.append(error_msg)
                errors_count += 1
                logger.exception(error_msg)

        return self._build_response(
            imported_count=imported_questions_count,
            detected_questions=len(questions),
            errors=errors,
            errors_count=errors_count,
            updated_count=updated_questions_count,
            ent_options_created=created_ent_options_count,
            duplicate_ent_options=duplicate_ent_options_count,
            skipped_questions_in_ent=skipped_questions_in_ent_count,
        )

    def _build_response(
        self,
        imported_count: int,
        detected_questions: int,
        errors: list[str],
        errors_count: int,
        trainers_updated: int = 0,
        updated_count: int = 0,
        ent_options_created: int = 0,
        duplicate_ent_options: int = 0,
        skipped_questions_in_ent: int = 0,
    ) -> dict:
        """Универсальный метод построения ответа для импорта"""
        result = {
            "detected_questions": detected_questions,
            "imported_questions_count": imported_count,
            "updated_questions_count": updated_count,
            "success": errors_count == 0,
            "errors_count": errors_count,
        }

        if trainers_updated > 0:
            result["trainers_updated"] = trainers_updated

        if ent_options_created > 0:
            result["ent_options_created"] = ent_options_created

        if duplicate_ent_options > 0:
            result["duplicate_ent_options"] = duplicate_ent_options

        if skipped_questions_in_ent > 0:
            result["skipped_questions_in_ent"] = skipped_questions_in_ent

        message_parts = []

        if imported_count > 0:
            message_parts.append(f"Создано {imported_count} новых вопросов")

        if updated_count > 0:
            message_parts.append(f"Обновлено {updated_count} вопросов (старые заменены новыми)")

        if trainers_updated > 0:
            message_parts.append(f"Обновлено {trainers_updated} тренажёров")

        if ent_options_created > 0:
            message_parts.append(f"Создано {ent_options_created} новых ЕНТ вариантов")

        if duplicate_ent_options > 0:
            message_parts.append(f"Пропущено {duplicate_ent_options} дубликатов ЕНТ вариантов")

        if skipped_questions_in_ent > 0:
            message_parts.append(
                f"Пропущено {skipped_questions_in_ent} вопросов, уже находящихся в других ЕНТ вариантах"
            )

        if errors_count > 0:
            message_parts.append(f"Найдено {errors_count} ошибок")

        result["message"] = ". ".join(message_parts) if message_parts else "Импорт завершен"

        if errors_count > 0:
            result["errors"] = errors

        return result
