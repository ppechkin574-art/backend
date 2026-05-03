import logging
from typing import Any

logger = logging.getLogger(__name__)


class AttemptStatisticCalculator:
    """Калькулятор статистики для разных типов попыток"""

    @staticmethod
    def calculate_trainer_statistic(attempt) -> dict[str, Any]:
        """Рассчитать статистику для тренажера"""
        total_questions = len(attempt.questions) if attempt.questions else 0

        if not total_questions:
            return {
                "correct": 0,
                "incorrect": 0,
                "skiped": 0,
                "total_questions": 0,
                "spend_time": 0,
                "score": 0,
            }

        correct = 0
        incorrect = 0
        skipped = 0
        total_spend_time = 0

        for question in attempt.questions:
            spend_time = getattr(question, "spend_time", 0)
            total_spend_time += spend_time

            if not question.answers or len(question.answers) == 0:
                skipped += 1
                continue

            correct_variant_ids = {variant.id for variant in question.question.variants if variant.is_correct}

            chosen_variant_ids = {answer.variant_id for answer in question.answers if answer.variant_id is not None}

            if correct_variant_ids and chosen_variant_ids == correct_variant_ids:
                correct += 1
            else:
                incorrect += 1

        score = correct

        return {
            "correct": correct,
            "incorrect": incorrect,
            "skiped": skipped,
            "total_questions": total_questions,
            "spend_time": int(total_spend_time),
            "score": score,
        }

    # @staticmethod
    # def calculate_ent_statistic(attempt, spend_time: int | None = None) -> dict[str, Any]:
    #     """Рассчитать статистику для ЕНТ"""

    #     total_questions = (
    #         len(attempt.full_exam_question_ids.split(","))
    #         if attempt.exam_type.value == "full_exam" and attempt.full_exam_question_ids
    #         else (len(attempt.options.questions) if attempt.options and attempt.options.questions else 0)
    #     )

    #     if not total_questions:
    #         return {
    #             "correct": 0,
    #             "incorrect": 0,
    #             "partial_correct": 0,
    #             "skiped": 0,
    #             "total_questions": 0,
    #             "spend_time": spend_time or 0,
    #             "score": 0,
    #         }

    #     return {
    #         "correct": 0,
    #         "incorrect": 0,
    #         "partial_correct": 0,
    #         "skiped": 0,
    #         "total_questions": total_questions,
    #         "spend_time": spend_time or 0,
    #         "score": attempt.score or 0,
    #     }

    # @staticmethod
    # def calculate_daily_test_statistic(attempt) -> dict[str, Any]:
    #     """Рассчитать статистику для ежедневного теста"""
    #     spend_time = 0
    #     if attempt.started_at and attempt.completed_at:
    #         spend_time = int((attempt.completed_at - attempt.started_at).total_seconds())

    #     return {
    #         "correct": attempt.correct_answers or 0,
    #         "incorrect": attempt.incorrect_answers or 0,
    #         "skiped": attempt.skipped_answers or 0,
    #         "total_questions": (
    #             (attempt.correct_answers or 0) + (attempt.incorrect_answers or 0) + (attempt.skipped_answers or 0)
    #         ),
    #         "spend_time": spend_time,
    #         "score": attempt.score or 0,
    #     }

    # @staticmethod
    # def calculate_generic_statistic(
    #     attempt,
    #     get_answers_func,
    #     get_questions_func,
    #     is_correct_func,
    #     spend_time_func=None,
    # ) -> dict[str, Any]:
    #     """Универсальный метод расчета статистики"""
    #     questions = get_questions_func(attempt)
    #     total_questions = len(questions)

    #     if not total_questions:
    #         return AttemptStatisticCalculator.get_empty_statistic()

    #     correct = 0
    #     incorrect = 0
    #     skipped = 0
    #     total_spend_time = 0

    #     for question in questions:
    #         if spend_time_func:
    #             spend_time = spend_time_func(question)
    #             total_spend_time += spend_time

    #         answers = get_answers_func(question)
    #         if not answers:
    #             skipped += 1
    #             continue

    #         if is_correct_func(question, answers):
    #             correct += 1
    #         else:
    #             incorrect += 1

    #     score = correct

    #     return {
    #         "correct": correct,
    #         "incorrect": incorrect,
    #         "skiped": skipped,
    #         "total_questions": total_questions,
    #         "spend_time": int(total_spend_time),
    #         "score": score,
    #     }

    # @staticmethod
    # def get_empty_statistic() -> dict[str, Any]:
    #     """Получить пустую статистику"""
    #     return {
    #         "correct": 0,
    #         "incorrect": 0,
    #         "skiped": 0,
    #         "total_questions": 0,
    #         "spend_time": 0,
    #         "score": 0,
    #     }
