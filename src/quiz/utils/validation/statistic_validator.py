import logging

# from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class StatisticValidator:
    """Валидатор статистических данных"""

    # @staticmethod
    # def validate_period_dates(start_date: date, end_date: date) -> bool:
    #     """Проверить корректность дат периода"""
    #     if start_date > end_date:
    #         return False

    #     return not end_date - start_date > timedelta(days=365)

    # @staticmethod
    # def validate_attempt_data(
    #     total_questions: int,
    #     correct_answers: int,
    #     incorrect_answers: int,
    #     skipped_answers: int,
    # ) -> bool:
    #     """Проверить корректность данных попытки"""
    #     if (
    #         total_questions < 0
    #         or correct_answers < 0
    #         or incorrect_answers < 0
    #         or skipped_answers < 0
    #     ):
    #         return False

    #     return correct_answers + incorrect_answers + skipped_answers == total_questions

    # @staticmethod
    # def validate_accuracy(accuracy: float) -> bool:
    #     """Проверить корректность значения точности"""
    #     return 0.0 <= accuracy <= 1.0

    @staticmethod
    def validate_statistics_consistency(statistics: dict[str, Any]) -> list[str]:
        """Проверить согласованность статистических данных"""
        errors = []

        total_questions = statistics.get("total_questions", 0)
        overall_accuracy = statistics.get("overall_accuracy", 0)

        if total_questions > 0 and overall_accuracy > 1.0:
            errors.append(f"Overall accuracy {overall_accuracy} > 1.0")

        for section in ["ent", "trainer", "daily"]:
            if section in statistics:
                section_data = statistics[section]
                total = section_data.get("total_questions", 0)
                correct = section_data.get("correct_answers", 0)

                if total > 0 and correct > total:
                    errors.append(f"{section}: correct answers {correct} > total {total}")

        return errors
