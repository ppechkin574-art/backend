import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


# class ActivityType(StrEnum):
#     """Types of activity for streak calculation"""

#     ANY = "any"
#     ENT = "ent"
#     TRAINER = "trainer"
#     DAILY = "daily"


class StreakCalculator:
    """Calculator for streaks of activity"""

    # @staticmethod
    # def calculate_current_streak(
    #     activity_dates: set[date],
    #     timezone_offset_hours: int = 0,
    #     include_today: bool = True,
    # ) -> int:
    #     """Calculate current streak"""
    #     if not activity_dates:
    #         return 0

    #     current_date = StreakCalculator._get_current_date(timezone_offset_hours)

    #     if not include_today and current_date not in activity_dates:
    #         return 0

    #     streak = 1 if current_date in activity_dates else 0
    #     if streak == 0:
    #         return 0

    #     current_check_date = current_date - timedelta(days=1)
    #     consecutive_days = 0

    #     while current_check_date in activity_dates:
    #         streak += 1
    #         consecutive_days += 1
    #         current_check_date -= timedelta(days=1)

    #         if consecutive_days > 365:
    #             break

    #     return streak

    @staticmethod
    def calculate_streak_on_date(
        activity_dates: set[date],
        target_date: date,
        include_target_date: bool = True,
    ) -> int:
        """Calculate streak on specific date"""
        if not activity_dates:
            return 0

        if not include_target_date and target_date not in activity_dates:
            return 0

        streak = 1 if target_date in activity_dates else 0
        if streak == 0:
            return 0

        current_check_date = target_date - timedelta(days=1)
        consecutive_days = 0

        while current_check_date in activity_dates:
            streak += 1
            consecutive_days += 1
            current_check_date -= timedelta(days=1)

            if consecutive_days > 365:
                break

        return streak

    # @staticmethod
    # def calculate_longest_streak(activity_dates: set[date]) -> int:
    #     """Calculate longest streak"""
    #     if not activity_dates:
    #         return 0

    #     sorted_dates = sorted(activity_dates)
    #     longest_streak = 1
    #     current_streak = 1
    #     prev_date = sorted_dates[0]

    #     for current_date in sorted_dates[1:]:
    #         if (current_date - prev_date).days == 1:
    #             current_streak += 1
    #             longest_streak = max(longest_streak, current_streak)
    #         else:
    #             current_streak = 1
    #         prev_date = current_date

    #     return longest_streak

    @staticmethod
    def calculate_max_streak_in_period(
        activity_dates: set[date],
        start_date: date,
        end_date: date,
    ) -> int:
        """Calculate max streak in period"""
        period_dates = {d for d in activity_dates if start_date <= d <= end_date}

        if not period_dates:
            return 0

        sorted_dates = sorted(period_dates)
        max_streak = 0
        current_streak = 0
        prev_date = sorted_dates[0] - timedelta(days=2)

        for current_date in sorted_dates:
            if (current_date - prev_date).days == 1:
                current_streak += 1
            else:
                current_streak = 1

            max_streak = max(max_streak, current_streak)
            prev_date = current_date

        return max_streak

    # @staticmethod
    # def calculate_all_streaks(
    #     ent_dates: set[date],
    #     trainer_dates: set[date],
    #     daily_dates: set[date],
    #     timezone_offset_hours: int = 0,
    # ) -> dict[str, int]:
    #     """Calculate all types of streaks"""
    #     all_dates = ent_dates | trainer_dates | daily_dates
    #     current_date = StreakCalculator._get_current_date(timezone_offset_hours)

    #     return {
    #         "ent": StreakCalculator.calculate_streak_on_date(ent_dates, current_date),
    #         "trainer": StreakCalculator.calculate_streak_on_date(trainer_dates, current_date),
    #         "daily": StreakCalculator.calculate_streak_on_date(daily_dates, current_date),
    #         "any": StreakCalculator.calculate_streak_on_date(all_dates, current_date),
    #     }

    @staticmethod
    def calculate_streak_period(
        activity_dates: set[date],
        start_date: date,
        end_date: date,
    ) -> tuple[int, dict[str, bool]]:
        """Calculate streak and activity history by period"""
        period_dates = {d for d in activity_dates if start_date <= d <= end_date}

        current_streak = StreakCalculator.calculate_streak_on_date(period_dates, end_date)

        streak_history = {}
        current_date = start_date

        while current_date <= end_date:
            streak_history[current_date.isoformat()] = current_date in period_dates
            current_date += timedelta(days=1)

        return current_streak, streak_history

    # @staticmethod
    # def _get_current_date(timezone_offset_hours: int) -> date:
    #     """Get current date in local time"""
    #     now_utc = datetime.now(UTC)
    #     local_time = now_utc + timedelta(hours=timezone_offset_hours)
    #     return local_time.date()

    @staticmethod
    def get_activity_level(
        total_attempts: int,
        period_days: int = 7,
    ) -> str:
        """Get activity level"""
        if period_days == 0:
            return "low"

        attempts_per_day = total_attempts / period_days

        if attempts_per_day >= 2.0:
            return "very_high"
        elif attempts_per_day >= 1.0:
            return "high"
        elif attempts_per_day >= 0.3:
            return "medium"
        else:
            return "low"
