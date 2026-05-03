import logging

# import math

logger = logging.getLogger(__name__)


class MathUtils:
    # @staticmethod
    # def calculate_median(values: list[float]) -> float:
    #     """Calculate median from list of values"""
    #     if not values:
    #         return 0.0

    #     sorted_values = sorted(values)
    #     n = len(sorted_values)

    #     if n % 2 == 1:
    #         return float(sorted_values[n // 2])
    #     else:
    #         middle1 = sorted_values[n // 2 - 1]
    #         middle2 = sorted_values[n // 2]
    #         return float((middle1 + middle2) / 2.0)

    # @staticmethod
    # def filter_valid_values(values: list[float | None]) -> list[float]:
    #     """Filter list of values and return only valid values"""
    #     valid_values = []
    #     for value in values:
    #         if value is not None and not math.isnan(value) and value > 0:
    #             valid_values.append(float(value))
    #     return valid_values

    @staticmethod
    def calculate_accuracy(correct: int, total: int) -> float:
        """Calculate accuracy"""
        return correct / total if total > 0 else 0.0

    # @staticmethod
    # def calculate_percentage(value: float, total: float) -> float:
    #     """Calculate percentage"""
    #     return (value / total * 100) if total > 0 else 0.0

    # @staticmethod
    # def normalize_value(value: float, min_val: float, max_val: float) -> float:
    #     """Normalize value between 0 and 1"""
    #     if max_val == min_val:
    #         return 0.0
    #     return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

    # @staticmethod
    # def calculate_weighted_average(values: list[float], weights: list[float]) -> float:
    #     """Calculate weighted average"""
    #     if not values or len(values) != len(weights):
    #         return 0.0

    #     weighted_sum = sum(v * w for v, w in zip(values, weights, strict=False))
    #     total_weight = sum(weights)

    #     return weighted_sum / total_weight if total_weight > 0 else 0.0
