from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from analytics.models import UserActivity
from quiz.models.attendance_streak import AttendanceLog, AttendanceStreak


class AttendanceRepository:
    def __init__(self, session: Session):
        self._session = session

    # def get_streak_by_student(self, student_guid: UUID) -> AttendanceStreak | None:
    #     return self._session.query(AttendanceStreak).filter(AttendanceStreak.student_guid == student_guid).first()

    # def create_streak(self, student_guid: UUID) -> AttendanceStreak:
    #     streak = AttendanceStreak(
    #         student_guid=student_guid,
    #         current_streak_days=0,
    #         longest_streak_days=0,
    #         total_points=0,
    #         current_cycle_days=0,
    #         completed_cycles_count=0,
    #     )
    #     self._session.add(streak)
    #     return streak

    # def get_today_log(self, streak_id: int) -> AttendanceLog | None:
    #     today = datetime.now(UTC).date()
    #     start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
    #     end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)

    #     return (
    #         self._session.query(AttendanceLog)
    #         .filter(
    #             AttendanceLog.attendance_streak_id == streak_id,
    #             AttendanceLog.activity_date >= start_of_day,
    #             AttendanceLog.activity_date <= end_of_day,
    #         )
    #         .first()
    #     )

    # def create_log(self, streak_id: int, points: int, streak_days: int, multiplier: int) -> AttendanceLog:
    #     log = AttendanceLog(
    #         attendance_streak_id=streak_id,
    #         activity_date=datetime.now(UTC),
    #         points_awarded=points,
    #         streak_days_at_activity=streak_days,
    #         multiplier_at_activity=multiplier,
    #     )
    #     self._session.add(log)
    #     return log

    # def get_streak_logs(self, streak_id: int, limit: int = 30) -> list[AttendanceLog]:
    #     return (
    #         self._session.query(AttendanceLog)
    #         .filter(AttendanceLog.attendance_streak_id == streak_id)
    #         .order_by(AttendanceLog.activity_date.desc())
    #         .limit(limit)
    #         .all()
    #     )

    # def get_streak_logs_by_date_range(self, streak_id: int, start_date: date, end_date: date) -> list[AttendanceLog]:
    #     start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=UTC)
    #     end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=UTC)

    #     return (
    #         self._session.query(AttendanceLog)
    #         .filter(
    #             AttendanceLog.attendance_streak_id == streak_id,
    #             AttendanceLog.activity_date >= start_datetime,
    #             AttendanceLog.activity_date <= end_datetime,
    #         )
    #         .order_by(AttendanceLog.activity_date.asc())
    #         .all()
    #     )

    def save(self) -> None:
        self._session.commit()

    # def get_log_by_date(self, streak_id: int, log_date: date) -> AttendanceLog | None:
    #     """
    #     Получить лог посещения за конкретную дату
    #     """
    #     start_of_day = datetime.combine(log_date, datetime.min.time()).replace(tzinfo=UTC)
    #     end_of_day = datetime.combine(log_date, datetime.max.time()).replace(tzinfo=UTC)

    #     return (
    #         self._session.query(AttendanceLog)
    #         .filter(
    #             AttendanceLog.attendance_streak_id == streak_id,
    #             AttendanceLog.activity_date >= start_of_day,
    #             AttendanceLog.activity_date <= end_of_day,
    #         )
    #         .first()
    #     )

    # def get_log_in_range(self, student_guid: UUID, start: datetime, end: datetime) -> AttendanceLog | None:
    #     return (
    #         self._session.query(AttendanceLog)
    #         .join(AttendanceStreak)
    #         .filter(
    #             AttendanceStreak.student_guid == student_guid,
    #             AttendanceLog.activity_date >= start,
    #             AttendanceLog.activity_date <= end,
    #         )
    #         .first()
    #     )

    def get_attendance_logs_for_feed(
        self, student_guid: UUID, limit: int, offset: int
    ) -> tuple[list[AttendanceLog], int]:
        query = (
            self._session.query(AttendanceLog)
            .join(AttendanceStreak)
            .filter(AttendanceStreak.student_guid == student_guid)
            .order_by(AttendanceLog.activity_date.desc())
        )
        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total

    def has_app_open_event(self, user_id: UUID, start_utc: datetime, end_utc: datetime) -> bool:
        """Проверить, было ли событие открытия приложения у пользователя в заданном интервале UTC."""
        return (
            self._session.query(UserActivity)
            .filter(
                UserActivity.user_id == user_id,
                UserActivity.event_name == "app_opened",
                UserActivity.event_time >= start_utc,
                UserActivity.event_time <= end_utc,
            )
            .first()
            is not None
        )
