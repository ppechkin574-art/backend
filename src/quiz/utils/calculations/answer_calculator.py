import logging
from typing import Any

logger = logging.getLogger(__name__)


class AnswerCalculator:
    @staticmethod
    def calculate_correctness(
        question_type: str, chosen_variant_ids: set[int], correct_variant_ids: set[int]
    ) -> tuple[bool, dict[str, Any]]:
        """Calculate correctness of answer"""
        if question_type == "single_choice":
            is_correct = bool(chosen_variant_ids) and bool(chosen_variant_ids & correct_variant_ids)
            details = {"type": "single_choice"}

        elif question_type == "multiple_choice":
            if correct_variant_ids:
                correct_selected = chosen_variant_ids & correct_variant_ids
                incorrect_selected = chosen_variant_ids - correct_variant_ids
                total_correct = len(correct_variant_ids)

                correct_weight = len(correct_selected) / total_correct if total_correct > 0 else 0
                is_correct = correct_selected == correct_variant_ids and not incorrect_selected
                details = {
                    "type": "multiple_choice",
                    "correct_selected": len(correct_selected),
                    "incorrect_selected": len(incorrect_selected),
                    "total_correct": total_correct,
                    "correct_weight": correct_weight,
                }
            else:
                is_correct = False
                details = {"type": "multiple_choice", "error": "no_correct_variants"}

        else:
            is_correct = False
            details = {"type": "unknown"}

        return is_correct, details

    # @staticmethod
    # def calculate_score(
    #     questions: list[dict[str, Any]],
    # ) -> dict[str, Any]:
    #     """Calculate score"""
    #     total_score = 0
    #     max_score = 0
    #     correct_count = 0
    #     incorrect_count = 0
    #     partial_correct_count = 0

    #     for question in questions:
    #         max_score += question.get("max_points", 1)

    #         if question.get("is_correct"):
    #             total_score += question.get("points", 1)
    #             correct_count += 1
    #         elif question.get("is_partial_correct"):
    #             total_score += question.get("partial_points", 0.5)
    #             partial_correct_count += 1
    #         elif question.get("is_answered"):
    #             incorrect_count += 1

    #     percentage = (total_score / max_score * 100) if max_score > 0 else 0

    #     return {
    #         "total_score": total_score,
    #         "max_score": max_score,
    #         "percentage": percentage,
    #         "correct_count": correct_count,
    #         "incorrect_count": incorrect_count,
    #         "partial_correct_count": partial_correct_count,
    #     }

    # @staticmethod
    # def calculate_ent_score(
    #     correct: int,
    #     partial_correct: int,
    #     correct_weight: float = 1.0,
    #     partial_weight: float = 0.5,
    # ) -> float:
    #     """Calculate score for ENT"""
    #     return (correct * correct_weight) + (partial_correct * partial_weight)
