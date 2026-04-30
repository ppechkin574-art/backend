from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from quiz.dtos.attendance import (
    AttendanceCalendarDTO,
    AttendanceCycleDTO,
    AttendanceDateDTO,
    AttendanceFullDTO,
    AttendanceStreakDTO,
)
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached


class AttendanceService:
    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service
        self.CYCLE_LENGTH = 5
        self.BASE_POINTS = 1

    # def _get_timezone_aware_date(self, dt: datetime | None = None) -> datetime:
    #     """Получить дату с учетом часового пояса"""
    #     if dt is None:
    #         return datetime.now(UTC)
    #     if dt.tzinfo is None:
    #         return dt.replace(tzinfo=UTC)
    #     return dt

    def _get_date_only(self, dt: datetime) -> date:
        """Получить только дату (без времени)"""
        return dt.date()

    def _get_user_activity_dates(self, session: Session, student_guid: UUID) -> list[date]:
        """Получить все уникальные даты активности пользователя"""
        from analytics.models import UserActivity

        activities = (
            session.query(UserActivity.event_time)
            .filter(
                UserActivity.user_id == student_guid,
                UserActivity.event_name.not_in(["app_backgrounded", "app_crashed"]),
            )
            .all()
        )

        dates = sorted({self._get_date_only(act[0]) for act in activities})
        return dates

    def _calculate_streak_from_dates(self, dates: list[date]) -> dict[str, Any]:
        """Рассчитать стрик на основе дат активности"""
        if not dates:
            return {
                "current_days": 0,
                "longest_days": 0,
                "total_points": 0,
                "current_cycle_day": 0,
                "completed_cycles": 0,
                "cycle_number": 1,
            }

        dates.sort()

        longest_streak = 1
        current_streak_in_loop = 1

        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                current_streak_in_loop += 1
                longest_streak = max(longest_streak, current_streak_in_loop)
            else:
                current_streak_in_loop = 1

        current_streak = 1
        for i in range(len(dates) - 2, -1, -1):
            if (dates[i + 1] - dates[i]).days == 1:
                current_streak += 1
            else:
                break

        completed_cycles = (current_streak - 1) // self.CYCLE_LENGTH

        current_cycle_day = current_streak % self.CYCLE_LENGTH
        if current_cycle_day == 0:
            current_cycle_day = self.CYCLE_LENGTH

        cycle_number = completed_cycles + 1

        total_points = 0
        streak_day_counter = 0

        for i in range(len(dates)):
            if i == 0 or (dates[i] - dates[i - 1]).days == 1:
                streak_day_counter += 1
            else:
                streak_day_counter = 1

            cycle_num_for_day = (streak_day_counter - 1) // self.CYCLE_LENGTH + 1
            points_for_day = self.BASE_POINTS * cycle_num_for_day
            total_points += points_for_day

        return {
            "current_days": current_streak,
            "longest_days": longest_streak,
            "total_points": total_points,
            "current_cycle_day": current_cycle_day,
            "completed_cycles": completed_cycles,
            "cycle_number": cycle_number,
        }

    # def _invalidate_attendance_cache(self, student_guid: UUID, date_str: str | None = None):
    #     """Инвалидировать кеш посещаемости"""
    #     resources = ["attendance_info"]

    #     if date_str:
    #         self._cache_service.delete(
    #             self._cache_service.make_key(
    #                 CacheStrategy.USER,
    #                 resource="attendance_info",
    #                 user_id=student_guid,
    #                 params=f"year:{date_str[:4]}:month:{date_str[5:7]}",
    #             )
    #         )
    #     else:
    #         self._cache_service.invalidate_by_resources(resources, user_id=student_guid)

    @cached(strategy=CacheStrategy.USER, ttl=86400, resource="attendance_info")
    def get_attendance_info(
        self,
        student_guid: UUID,
        year: int | None = None,
        month: int | None = None,
    ) -> AttendanceFullDTO:
        """Получить полную информацию о посещениях"""
        with self._uow:
            all_dates = self._get_user_activity_dates(self._uow.session, student_guid)

            streak_data = self._calculate_streak_from_dates(all_dates)

            current_date = datetime.now(UTC).date()

            if year is None:
                year = current_date.year
            if month is None:
                month = current_date.month

            calendar_data = self._get_calendar_for_month(all_dates, year, month)

            today_points = None
            if current_date in all_dates:
                today_index = all_dates.index(current_date)

                streak_counter = 1
                for i in range(today_index - 1, -1, -1):
                    if (all_dates[i + 1] - all_dates[i]).days == 1:
                        streak_counter += 1
                    else:
                        break

                cycle_num = (streak_counter - 1) // self.CYCLE_LENGTH + 1
                today_points = self.BASE_POINTS * cycle_num

            days_to_next_cycle = self.CYCLE_LENGTH - streak_data["current_cycle_day"] + 1

            return AttendanceFullDTO(
                streak=AttendanceStreakDTO(
                    current_days=streak_data["current_days"],
                    longest_days=streak_data["longest_days"],
                    total_points=streak_data["total_points"],
                    today_points=today_points,
                ),
                cycle=AttendanceCycleDTO(
                    current_day=streak_data["current_cycle_day"],
                    cycle_number=streak_data["cycle_number"],
                    completed_cycles=streak_data["completed_cycles"],
                    days_to_next_cycle=days_to_next_cycle,
                    current_multiplier=streak_data["cycle_number"],
                ),
                calendar=calendar_data,
            )

    def _get_calendar_for_month(self, all_dates: list[date], year: int, month: int) -> AttendanceCalendarDTO:
        """Получить данные календаря за конкретный месяц"""
        month_dates = [d for d in all_dates if d.year == year and d.month == month]

        details = []

        streak_day_by_date = {}
        current_streak = 0
        prev_date = None

        for d in sorted(all_dates):
            if prev_date is None or (d - prev_date).days == 1:
                current_streak += 1
            else:
                current_streak = 1
            streak_day_by_date[d] = current_streak
            prev_date = d

        for activity_date in month_dates:
            streak_day = streak_day_by_date[activity_date]

            cycle_num = (streak_day - 1) // self.CYCLE_LENGTH + 1
            cycle_day = ((streak_day - 1) % self.CYCLE_LENGTH) + 1
            points = self.BASE_POINTS * cycle_num

            details.append(
                AttendanceDateDTO(
                    date=activity_date,
                    points=points,
                    streak_day=streak_day,
                    cycle_day=cycle_day,
                    multiplier=cycle_num,
                )
            )

        return AttendanceCalendarDTO(year=year, month=month, attendance_dates=month_dates, details=details)
