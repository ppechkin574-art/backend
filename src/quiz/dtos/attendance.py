from datetime import date

from pydantic import BaseModel


class AttendanceDateDTO(BaseModel):
    """DTO для даты посещения"""

    date: date
    points: int
    streak_day: int
    cycle_day: int
    multiplier: int


class AttendanceCalendarDTO(BaseModel):
    """DTO для календаря за месяц"""

    year: int
    month: int
    attendance_dates: list[date]
    details: list[AttendanceDateDTO]


class AttendanceCycleDTO(BaseModel):
    """DTO для информации о текущем цикле"""

    current_day: int
    cycle_number: int
    completed_cycles: int
    days_to_next_cycle: int
    current_multiplier: int


class AttendanceStreakDTO(BaseModel):
    """DTO для информации о стрике"""

    current_days: int
    longest_days: int
    total_points: int
    today_points: int | None = None


class AttendanceFullDTO(BaseModel):
    """Полный DTO со всей информацией о посещаемости"""

    streak: AttendanceStreakDTO
    cycle: AttendanceCycleDTO
    calendar: AttendanceCalendarDTO


class AttendanceMonthRequestDTO(BaseModel):
    """DTO для запроса данных за месяц"""

    year: int
    month: int
