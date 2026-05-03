from datetime import date, timedelta

from quiz.dtos.statistic import StatisticPeriodType, StatisticRequestDTO


class PeriodCalculator:
    @staticmethod
    def calculate_period_dates(request: StatisticRequestDTO) -> tuple[date, date, str]:
        """Calculate period dates based on request"""
        today = date.today()

        if request.period_type == StatisticPeriodType.LAST_7_DAYS:
            start_date = today - timedelta(days=6)
            end_date = today
            description = f"Last 7 days ({start_date} - {end_date})"

        elif request.period_type == StatisticPeriodType.LAST_30_DAYS:
            start_date = today - timedelta(days=29)
            end_date = today
            description = f"Last 30 days ({start_date} - {end_date})"

        elif request.period_type == StatisticPeriodType.CALENDAR_WEEK:
            target_date = request.week_date or today

            start_date = target_date - timedelta(days=target_date.weekday())
            end_date = start_date + timedelta(days=6)
            description = f"Calendar week {start_date.isocalendar().week} ({start_date} - {end_date})"

        elif request.period_type == StatisticPeriodType.CALENDAR_MONTH:
            year, month = PeriodCalculator._parse_month_year(request.month_year)
            start_date = date(year, month, 1)
            end_date = PeriodCalculator._get_last_day_of_month(year, month)
            description = f"Calendar month {month}.{year} ({start_date} - {end_date})"

        else:
            if request.custom_start_date and request.custom_end_date:
                start_date = request.custom_start_date
                end_date = request.custom_end_date
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                description = f"Custom period ({start_date} - {end_date})"
            else:
                start_date = today - timedelta(days=6)
                end_date = today
                description = f"Default last period {start_date} - {end_date})"

        return start_date, end_date, description

    @staticmethod
    def _parse_month_year(month_year: str | None) -> tuple[int, int]:
        """Parse month and year from string"""
        if not month_year:
            today = date.today()
            return today.year, today.month

        parts = month_year.split("-")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        elif len(parts) == 1:
            return date.today().year, int(month_year)
        else:
            raise ValueError(f"Invalid format month_year: {month_year}")

    @staticmethod
    def _get_last_day_of_month(year: int, month: int) -> date:
        """Get last day of month"""
        if month == 12:
            return date(year + 1, 1, 1) - timedelta(days=1)
        else:
            return date(year, month + 1, 1) - timedelta(days=1)

    @staticmethod
    def get_period_days(start_date: date, end_date: date) -> int:
        """Get period days"""
        return (end_date - start_date).days + 1

    # @staticmethod
    # def generate_date_range(start_date: date, end_date: date) -> list[date]:
    #     """Generate date range"""
    #     dates = []
    #     current_date = start_date
    #     while current_date <= end_date:
    #         dates.append(current_date)
    #         current_date += timedelta(days=1)
    #     return dates
