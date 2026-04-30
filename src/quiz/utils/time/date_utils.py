from datetime import UTC, datetime, timezone


class DateUtils:
    # @staticmethod
    # def get_local_date(timezone_offset_hours: int = 5) -> date:
    #     """Get current date in local time"""
    #     return (datetime.now(UTC) + timedelta(hours=timezone_offset_hours)).date()

    # @staticmethod
    # def utc_to_local(dt: datetime, timezone_offset_hours: int = 5) -> datetime:
    #     """Convert UTC time to local"""
    #     if dt.tzinfo is None:
    #         dt = dt.replace(tzinfo=UTC)
    #     return dt + timedelta(hours=timezone_offset_hours)

    # @staticmethod
    # def local_to_utc(dt: datetime, timezone_offset_hours: int = 5) -> datetime:
    #     """Convert local time to UTC"""
    #     return dt - timedelta(hours=timezone_offset_hours)

    @staticmethod
    def ensure_timezone(dt: datetime, default_tz: timezone = UTC) -> datetime:
        """Guarantee that the datetime has a timezone"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=default_tz)
        return dt

    # @staticmethod
    # def get_dates_in_range(start_date: date, end_date: date) -> list[date]:
    #     """Get dates in range"""
    #     dates = []
    #     current_date = start_date
    #     while current_date <= end_date:
    #         dates.append(current_date)
    #         current_date += timedelta(days=1)
    #     return dates
