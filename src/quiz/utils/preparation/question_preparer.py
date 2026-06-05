import logging
from typing import Any

from quiz.dtos.questions import QuestionRepositoryDTO, QuestionServiceDTO
from quiz.utils.hint_transform import transform_video_hint

logger = logging.getLogger(__name__)


class QuestionPreparer:
    @staticmethod
    def prepare_question_with_answers(
        question_obj: Any,
        user_variant_ids: list[int],
        question_number: int = 1,
        include_hint: bool = True,
    ) -> dict[str, Any]:
        """Prepare question with user answers"""
        if isinstance(question_obj, QuestionServiceDTO):
            question_dto = question_obj
        elif isinstance(question_obj, QuestionRepositoryDTO):
            from quiz.converters import to_service_question

            question_dto = to_service_question(question_obj)
        else:
            question_repo = QuestionRepositoryDTO.custom(question_obj)
            from quiz.converters import to_service_question

            question_dto = to_service_question(question_repo)

        correct_variant_ids = {variant.id for variant in question_dto.variants if variant.is_correct}

        prepared_variants = []
        for variant in question_dto.variants:
            prepared_variants.append(
                {
                    "id": variant.id,
                    "blocks": variant.blocks,
                    "is_correct": variant.is_correct,
                    "weight": variant.weight,
                    "user_selected": variant.id in user_variant_ids,
                }
            )

        is_correct = None
        if user_variant_ids:
            is_correct = set(user_variant_ids) == correct_variant_ids

        hint = question_dto.hint
        if include_hint and hint:
            hint = transform_video_hint(hint)

        return {
            "id": question_dto.id,
            "guid": question_dto.guid,
            "topic_id": question_dto.topic_id,
            "subject_id": question_dto.subject_id,
            "difficulty": question_dto.difficulty,
            "type": question_dto.type,
            "blocks": question_dto.blocks,
            "hint": hint,
            "variants": prepared_variants,
            "question_number": question_number,
            "is_correct": is_correct,
            "topic_name": getattr(question_dto, "topic_name", None),
            "subject_name": getattr(question_dto, "subject_name", None),
            "correct_variant_ids": list(correct_variant_ids),
            "user_variant_ids": user_variant_ids,
            "task_description_ru": getattr(question_dto, "task_description_ru", None),
            "task_description_kk": getattr(question_dto, "task_description_kk", None),
            "question_translation_ru": getattr(question_dto, "question_translation_ru", None),
            "question_translation_kk": getattr(question_dto, "question_translation_kk", None),
            "explanation_ru": getattr(question_dto, "explanation_ru", None),
            "explanation_kk": getattr(question_dto, "explanation_kk", None),
        }

    # @staticmethod
    # def prepare_questions_batch(
    #     questions: list[Any],
    #     user_answers_map: dict[int, list[int]],
    #     start_index: int = 1,
    # ) -> list[dict[str, Any]]:
    #     """Prepare batch of questions with user answers"""
    #     prepared_questions = []

    #     for idx, question in enumerate(questions):
    #         user_variant_ids = user_answers_map.get(question.id, [])
    #         prepared = QuestionPreparer.prepare_question_with_answers(
    #             question_obj=question,
    #             user_variant_ids=user_variant_ids,
    #             question_number=idx + start_index,
    #         )
    #         prepared_questions.append(prepared)

    #     return prepared_questions

    # @staticmethod
    # def transform_questions_with_answers(
    #     questions: list[Any],
    #     user_answers_map: dict[int, list[int]],
    #     start_index: int = 1,
    # ) -> list[dict[str, Any]]:
    #     """Transform questions with user answers"""
    #     return QuestionPreparer.prepare_questions_batch(
    #         questions, user_answers_map, start_index
    #     )

    # @staticmethod
    # def extract_subject_info(question_obj: Any) -> dict[str, str | None]:
    #     """Extract subject info"""
    #     subject_name = None
    #     topic_name = None

    #     if hasattr(question_obj, "subject") and question_obj.subject:
    #         subject_name = getattr(question_obj.subject, "name", None)
    #     elif hasattr(question_obj, "subject_name"):
    #         subject_name = question_obj.subject_name

    #     if hasattr(question_obj, "topic") and question_obj.topic:
    #         topic_name = getattr(question_obj.topic, "name", None)
    #     elif hasattr(question_obj, "topic_name"):
    #         topic_name = question_obj.topic_name

    #     return {
    #         "subject_name": subject_name,
    #         "topic_name": topic_name,
    #     }
