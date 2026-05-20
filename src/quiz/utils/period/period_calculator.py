from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from quiz.dtos.statistic import StatisticPeriodType, StatisticRequestDTO

# Aima is a Kazakhstan-only product, so the "current day" used for stats
# (and the streak in particular) is the local Almaty day, not the server's
# UTC day. Railway containers run in UTC, so `date.today()` returns a UTC
# date that's off by 5 hours from what a KZ user perceives — a task
# solved at 01:00 Almaty time would get bucketed into the previous day,
# breaking late-night streaks.
KZ_TZ = ZoneInfo("Asia/Almaty")


def today_kz() -> date:
    """Today's date in Asia/Almaty time. Use this everywhere we need
    a "current calendar day" for KZ-facing stats — never `date.today()`."""
    return datetime.now(KZ_TZ).date()


def to_kz_date(dt: datetime | None) -> date | None:
    """Convert a database datetime (naive UTC, our convention) or a
    timezone-aware datetime to the Almaty calendar date that contains it.
    Returns None on None input — useful for `if dt else None`-style
    list comprehensions on optional columns."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KZ_TZ).date()


def kz_day_window_utc(start_kz: date, end_kz: date) -> tuple[datetime, datetime]:
    """Return naive-UTC datetimes that bracket the calendar window
    [start_kz 00:00 KZ, end_kz 23:59:59.999999 KZ] for use in DB queries
    against naive-UTC `completed_at` columns. Without this, the period
    window is shifted by 5 hours and late-night activity falls outside
    the query range — leading to a streak that "skips" days the user
    actually trained.
    """
    start_dt_utc = datetime.combine(start_kz, time.min, tzinfo=KZ_TZ).astimezone(UTC).replace(tzinfo=None)
    end_dt_utc = datetime.combine(end_kz, time.max, tzinfo=KZ_TZ).astimezone(UTC).replace(tzinfo=None)
    return start_dt_utc, end_dt_utc


class PeriodCalculator:
    @staticmethod
    def calculate_period_dates(request: StatisticRequestDTO) -> tuple[date, date, str]:
        """Calculate period dates based on request"""
        today = today_kz()

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
            today = today_kz()
            return today.year, today.month

        parts = month_year.split("-")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        elif len(parts) == 1:
            return today_kz().year, int(month_year)
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
