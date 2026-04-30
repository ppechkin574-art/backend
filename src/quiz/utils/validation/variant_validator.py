import logging

from quiz.exceptions import VariantNotExist

logger = logging.getLogger(__name__)


class VariantValidator:
    """Validator for variants of answers"""

    @staticmethod
    def validate_variants_belong_to_question(
        question_id: int,
        variant_ids: list[int],
        valid_variant_ids: set[int],
    ) -> None:
        """Check if variants belong to question"""
        for variant_id in variant_ids:
            if variant_id not in valid_variant_ids:
                raise VariantNotExist(
                    f"Variant {variant_id} does not belong to question {question_id}. "
                    f"Valid variants: {list(valid_variant_ids)}"
                )

        logger.info("All variants validated successfully for question %s", question_id)

    @staticmethod
    def get_valid_variant_ids(question) -> set[int]:
        """Get valid variant ids from question"""
        return {variant.id for variant in question.variants}
