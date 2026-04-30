import logging
import re
from typing import Any, Protocol

import pandas as pd
from pandas.errors import EmptyDataError

from quiz.dtos.ent_options import EntOptionCreateDTO
from quiz.dtos.enums import BlockType, Difficulty, QuestionType, TestType
from quiz.dtos.questions import ImportQuestionCreateDTO
from quiz.dtos.text_blocks import TextBlockServiceDTO
from quiz.dtos.variants import ImportVariantCreateDTO
from quiz.exceptions import InvalidFormat, MissingColumns, TestTypeDontImport

logger = logging.getLogger(__name__)


class QuestionParserInterface(Protocol):
    def parse(self, source: Any) -> list[ImportQuestionCreateDTO]:
        raise NotImplementedError


class QuestionParserXLSX:
    """Парсер для Excel файлов с вопросами"""

    _expected_columns = {
        TestType.ent: {
            "номер варианта": "option_number",
            "номер вопроса": "question_number",
            "предмет": "subject",
            "вопрос ( текст / ссылка )": "question",
            "варианты ответа ( текст / ссылка )": "variants",
            "правильный вариант": "correct_answer",
        },
        TestType.training: {
            "номер варианта": "option_number",
            "номер вопроса": "question_number",
            "предмет": "subject",
            "вопрос ( текст / ссылка )": "question",
            "варианты ответа ( текст / ссылка )": "variants",
            "правильный вариант": "correct_answer",
        },
    }

    _difficulty_mapper = {
        "легкий": Difficulty.easy,
        "легкое": Difficulty.easy,
        "средний": Difficulty.medium,
        "среднее": Difficulty.medium,
        "сложный": Difficulty.hard,
        "сложное": Difficulty.hard,
        "easy": Difficulty.easy,
        "medium": Difficulty.medium,
        "hard": Difficulty.hard,
    }

    def _extract_blocks(self, content: str) -> list[TextBlockServiceDTO]:
        """
        Метод для извлечения блоков из строки с текстом и URL
        Фигурные скобки {} удаляются только для медиа-ссылок (изображения/видео)
        Для LaTeX формул и другого текста фигурные скобки сохраняются
        """
        if not content or pd.isna(content):
            return []

        content = str(content).strip()
        if not content:
            return []

        blocks = []
        order = 0

        media_in_braces_pattern = (
            r"\{(\s*(https?://[^}{]+\.(?:jpg|jpeg|png|gif|bmp|webp|mp4|avi|mov)(?:\?[^}{]*)?)\s*)\}"
        )

        media_pattern = r"(https?://[^\s]+\.(?:jpg|jpeg|png|gif|bmp|webp|mp4|avi|mov)(?:\?[^\s]*)?)"

        parts = []
        current_pos = 0

        media_in_braces_matches = list(re.finditer(media_in_braces_pattern, content, re.IGNORECASE))

        if media_in_braces_matches:
            for match in media_in_braces_matches:
                before_text = content[current_pos : match.start()]
                if before_text:
                    parts.append(("text", before_text))

                media_url = match.group(2)
                if media_url:
                    parts.append(("media", media_url.strip()))

                current_pos = match.end()

        remaining_text = content[current_pos:]

        if remaining_text:
            if current_pos == 0:
                sub_matches = list(re.finditer(media_pattern, remaining_text, re.IGNORECASE))
                sub_current_pos = 0

                for sub_match in sub_matches:
                    before_text = remaining_text[sub_current_pos : sub_match.start()]
                    if before_text:
                        parts.append(("text", before_text))

                    media_url = sub_match.group(1)
                    parts.append(("media", media_url.strip()))

                    sub_current_pos = sub_match.end()

                final_text = remaining_text[sub_current_pos:]
                if final_text:
                    parts.append(("text", final_text))
            else:
                parts.append(("text", remaining_text))

        if not parts:
            return [TextBlockServiceDTO(order=0, type=BlockType.text, value=content)]

        for part_type, part_value in parts:
            if not part_value or not str(part_value).strip():
                continue

            part_value = str(part_value).strip()

            if part_type == "media":
                if re.match(r"^https?://", part_value, re.IGNORECASE):
                    blocks.append(TextBlockServiceDTO(order=order, type=BlockType.media, value=part_value))
                    order += 1
                else:
                    blocks.append(TextBlockServiceDTO(order=order, type=BlockType.text, value=part_value))
                    order += 1
            else:
                blocks.append(TextBlockServiceDTO(order=order, type=BlockType.text, value=part_value))
                order += 1

        if len(blocks) > 1:
            merged_blocks = []
            i = 0
            while i < len(blocks):
                current_block = blocks[i]
                if (
                    current_block.type == BlockType.text
                    and i + 1 < len(blocks)
                    and blocks[i + 1].type == BlockType.text
                ):
                    combined_text = current_block.value
                    j = i + 1
                    while j < len(blocks) and blocks[j].type == BlockType.text:
                        combined_text += " " + blocks[j].value
                        j += 1

                    merged_blocks.append(
                        TextBlockServiceDTO(
                            order=len(merged_blocks),
                            type=BlockType.text,
                            value=combined_text.strip(),
                        )
                    )
                    i = j
                else:
                    current_block.order = len(merged_blocks)
                    merged_blocks.append(current_block)
                    i += 1

            blocks = merged_blocks

        return blocks

    def _validate_and_sanitize(self, value: Any, field_name: str, question_info: str = "") -> str:
        """Валидирует и очищает значение"""
        if pd.isna(value) or not str(value).strip():
            raise InvalidFormat(f"Отсутствует значение для '{field_name}' {question_info}")

        return str(value).strip()

    def _parse_difficulty(self, difficulty_str: str) -> Difficulty:
        """Парсит сложность из строки"""
        if not difficulty_str or pd.isna(difficulty_str):
            return Difficulty.easy

        difficulty_lower = difficulty_str.lower().strip()
        return self._difficulty_mapper.get(difficulty_lower, Difficulty.easy)

    def _group_questions(self, df: pd.DataFrame, test_type: TestType) -> dict:
        """Группирует вопросы по вариантам и номерам вопросов"""
        groups = {}
        current_group = None

        for idx, row in df.iterrows():
            try:
                is_new_question = False

                if test_type == TestType.training:
                    is_new_question = (
                        pd.notna(row.get("номер вопроса"))
                        and pd.notna(row.get("предмет"))
                        and pd.notna(row.get("тема"))
                        and str(row.get("номер вопроса")).strip() != ""
                        and str(row.get("предмет")).strip() != ""
                        and str(row.get("тема")).strip() != ""
                    )
                else:
                    is_new_question = (
                        pd.notna(row.get("номер варианта"))
                        and pd.notna(row.get("номер вопроса"))
                        and pd.notna(row.get("предмет"))
                        and str(row.get("номер варианта")).strip() != ""
                        and str(row.get("номер вопроса")).strip() != ""
                        and str(row.get("предмет")).strip() != ""
                    )

                if is_new_question:
                    option_num = int(float(row["номер варианта"])) if pd.notna(row["номер варианта"]) else 1
                    question_num = int(float(row["номер вопроса"])) if pd.notna(row["номер вопроса"]) else 1

                    if test_type == TestType.training:
                        topic = str(row["тема"]).strip().capitalize() if pd.notna(row["тема"]) else "Общая тема"
                    else:
                        topic = "Общая тема"

                    group_key = (option_num, question_num, topic)
                    current_group = group_key

                    if group_key not in groups:
                        groups[group_key] = []

                    groups[group_key].append(row)
                    logger.info("Started new question group: %s", group_key)

                elif current_group is not None:
                    groups[current_group].append(row)
                    logger.info("Added variant to existing group: %s", current_group)
                else:
                    logger.warning("Skipping row %s - no active question group", idx)

            except (ValueError, TypeError) as e:
                logger.warning("Ошибка парсинга строки %s: %s", idx, e)
                continue

        logger.info("Final grouping: %s groups created", len(groups))
        return groups

    def _parse_correct_answers(self, correct_answer_str: str) -> list[str]:
        """Парсит правильные ответы из строки, поддерживая несколько вариантов через ;"""
        if not correct_answer_str or pd.isna(correct_answer_str):
            return []

        correct_str = str(correct_answer_str).strip()
        if not correct_str or correct_str.lower() == "nan":
            return []

        answers = [ans.strip() for ans in correct_str.split(";")]
        return [ans for ans in answers if ans]

    def _get_variant_representation(self, variant_blocks: list[TextBlockServiceDTO]) -> str:
        """
        Получает текстовое представление варианта ответа.
        """
        representations = []
        for block in variant_blocks:
            representations.append(block.value.strip())
        return " ".join(representations)

    def _is_variant_correct(self, variant_blocks: list[TextBlockServiceDTO], correct_answers: list[str]) -> bool:
        """
        Определяет, является ли вариант правильным.
        Сравнивает текстовое содержание варианта с правильными ответами.
        """
        if not variant_blocks or not correct_answers:
            return False

        variant_repr = self._get_variant_representation(variant_blocks)
        if not variant_repr:
            return False

        clean_variant = " ".join(variant_repr.split()).lower()

        for correct_answer in correct_answers:
            correct_blocks = self._extract_blocks(correct_answer)
            correct_repr = self._get_variant_representation(correct_blocks)

            if not correct_repr:
                continue

            clean_correct = " ".join(correct_repr.split()).lower()

            if clean_variant == clean_correct:
                return True

            if clean_correct in clean_variant or clean_variant in clean_correct:
                return True

        return False

    def _determine_question_type(self, correct_answers: list[str]) -> QuestionType:
        """Определяет тип вопроса на основе количества правильных ответов"""
        if len(correct_answers) > 1:
            return QuestionType.multiple_choice
        return QuestionType.single_choice

    def _process_question_group(
        self, group: list[pd.Series], test_type: TestType, group_key
    ) -> ImportQuestionCreateDTO:
        """Обрабатывает группу строк, относящихся к одному вопросу"""
        if not group:
            raise InvalidFormat("Пустая группа вопросов")

        option_num, question_num, topic = group_key
        question_info = f"(вариант {option_num}, вопрос {question_num}, тема '{topic}')"

        first_row = group[0]

        try:
            subject = self._validate_and_sanitize(first_row["предмет"], "предмет", question_info)
            question_content = self._validate_and_sanitize(
                first_row["вопрос ( текст / ссылка )"], "вопрос", question_info
            )

            correct_answers = self._parse_correct_answers(first_row["правильный вариант"])
            if not correct_answers:
                raise InvalidFormat(f"Нет правильных ответов {question_info}")

            question_blocks = self._extract_blocks(question_content)
            if not question_blocks:
                raise InvalidFormat(f"Вопрос не может быть пустым {question_info}")

            question_type = self._determine_question_type(correct_answers)

            variants = []
            variant_contents = set()

            for row in group:
                if pd.notna(row["варианты ответа ( текст / ссылка )"]):
                    variant_content = str(row["варианты ответа ( текст / ссылка )"]).strip()
                    if variant_content and variant_content.lower() != "nan" and variant_content not in variant_contents:
                        variant_blocks = self._extract_blocks(variant_content)
                        if variant_blocks:
                            is_correct = self._is_variant_correct(variant_blocks, correct_answers)

                            weight = 1.0 if is_correct else 0.0
                            if question_type == QuestionType.multiple_choice and is_correct:
                                weight = 1.0 / len(correct_answers)

                            variants.append(
                                ImportVariantCreateDTO(
                                    blocks=variant_blocks,
                                    is_correct=is_correct,
                                    weight=weight,
                                )
                            )
                            variant_contents.add(variant_content)

            if not variants:
                raise InvalidFormat(f"Нет вариантов ответа {question_info}")

            correct_count = sum(1 for v in variants if v.is_correct)
            if correct_count == 0:
                logger.warning(
                    "Not found correct answers for question: %s, try to find them in variants",
                    question_info,
                )
                for variant in variants:
                    variant_repr = self._get_variant_representation(variant.blocks)
                    for correct_answer in correct_answers:
                        if (
                            correct_answer.lower() in variant_repr.lower()
                            or variant_repr.lower() in correct_answer.lower()
                        ):
                            variant.is_correct = True
                            if question_type == QuestionType.multiple_choice:
                                variant.weight = 1.0 / len(correct_answers)
                            else:
                                variant.weight = 1.0
                            correct_count += 1
                            logger.info("Finded correct answer: %s", variant_repr)
                            break

                if correct_count == 0:
                    raise InvalidFormat(f"Нет правильных вариантов среди вариантов ответа {question_info}")

            logger.info(
                "Created question with %s variants (%s correct) for %s",
                len(variants),
                correct_count,
                question_info,
            )

            ent_option_number = option_num if test_type == TestType.ent else None

            difficulty = Difficulty.easy
            hint_blocks = None

            if test_type == TestType.training:
                if "сложность" in first_row and pd.notna(first_row["сложность"]):
                    difficulty_str = str(first_row["сложность"]).strip()
                    difficulty = self._parse_difficulty(difficulty_str)

                if "подсказка" in first_row and pd.notna(first_row["подсказка"]):
                    hint_content = str(first_row["подсказка"]).strip()
                    if hint_content and hint_content.lower() != "nan":
                        hint_blocks = self._extract_blocks(hint_content)

            return ImportQuestionCreateDTO(
                question_blocks=question_blocks,
                answers=variants,
                hint_blocks=hint_blocks,
                subject=subject,
                topic_name=topic,
                difficulty=difficulty,
                ent_option_number=ent_option_number,
                type=question_type,
            )

        except Exception as e:
            logger.exception("Ошибка обработки группы вопросов %s: %s", group_key, str(e))
            raise

    def _create_ent_options(self, groups: dict) -> list[EntOptionCreateDTO]:
        """Создает объекты ENT вариантов на основе групп вопросов"""
        ent_options = set()

        for group_key in groups:
            if isinstance(group_key, tuple):
                option_num = group_key[0]
                ent_options.add(option_num)

        return [EntOptionCreateDTO(option_number=opt_num) for opt_num in sorted(ent_options)]

    def parse(
        self, data: Any
    ) -> tuple[
        list[ImportQuestionCreateDTO],
        list[EntOptionCreateDTO] | None,
        list[str],
        int,
    ]:
        try:
            df = pd.read_excel(data.file.file, engine="openpyxl")
            logger.info("Successfully read Excel file with %s rows", len(df))
        except EmptyDataError:
            raise InvalidFormat("Excel файл пуст или не может быть прочитан")
        except Exception as e:
            raise InvalidFormat(f"Ошибка чтения Excel файла: {str(e)}")

        df.columns = df.columns.str.strip().str.lower()
        logger.info("Columns found: %s", ", ".join(df.columns))

        test_type = data.type
        if test_type not in self._expected_columns:
            raise TestTypeDontImport(f"Неподдерживаемый тип теста: {test_type}")

        expected_cols = set(self._expected_columns[test_type].keys())
        missing_cols = expected_cols - set(df.columns)

        if missing_cols:
            raise MissingColumns(f"Отсутствуют обязательные колонки: {missing_cols}")

        groups = self._group_questions(df, test_type)
        logger.info("Grouped into %s question groups", len(groups))

        questions = []
        errors = []
        errors_count = 0

        for group_key, group_rows in groups.items():
            try:
                question_dto = self._process_question_group(group_rows, test_type, group_key)
                questions.append(question_dto)
                logger.info("Successfully parsed question group %s", group_key)
            except InvalidFormat as e:
                errors_count += 1
                error_msg = str(e)
                errors.append(error_msg)
                logger.exception("Validation error in group %s: %s", group_key, error_msg)
            except Exception as e:
                errors_count += 1
                error_msg = f"Неизвестная ошибка при обработке группы {group_key}: {str(e)}"
                errors.append(error_msg)
                logger.exception(error_msg)

        ent_options = None
        if test_type == TestType.ent:
            subject_errors = self._validate_ent_option_subjects(groups)
            errors.extend(subject_errors)
            errors_count += len(subject_errors)
            ent_options = self._create_ent_options(groups)
            logger.info("Created %s ENT options", len(ent_options))

        logger.info("Parser completed: %s questions, %s errors", len(questions), errors_count)
        return questions, ent_options, errors, errors_count

    def _validate_ent_option_subjects(self, groups: dict) -> list[str]:
        """Проверяет, что в каждом ЕНТ варианте все вопросы одного предмета"""
        errors = []

        options_subjects = {}
        for group_key, group_rows in groups.items():
            option_num = group_key[0]
            first_row = group_rows[0]
            subject = str(first_row["предмет"]).strip()

            if option_num not in options_subjects:
                options_subjects[option_num] = subject
            else:
                if options_subjects[option_num] != subject:
                    error_msg = f"В варианте {option_num} обнаружены разные предметы: {options_subjects[option_num]} и {subject}"
                    errors.append(error_msg)

        return errors
