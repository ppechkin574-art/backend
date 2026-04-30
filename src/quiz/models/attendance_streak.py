from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    func,
)
from sqlalchemy.orm import relationship

from database import Base


class AttendanceStreak(Base):
    __tablename__ = "attendance_streaks"

    id = Column(Integer, primary_key=True)
    student_guid = Column(UUID(as_uuid=True), nullable=False, index=True)
    current_streak_days = Column(Integer, default=0)
    longest_streak_days = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    current_cycle_days = Column(Integer, default=0)
    completed_cycles_count = Column(Integer, default=0)
    last_activity_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    attendance_logs = relationship(
        "AttendanceLog",
        back_populates="attendance_streak",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<AttendanceStreak {self.student_guid}: {self.current_streak_days} days>"


class AttendanceLog(Base):
    __tablename__ = "attendance_logs"

    id = Column(Integer, primary_key=True)
    attendance_streak_id = Column(Integer, ForeignKey("attendance_streaks.id"), nullable=False)
    activity_date = Column(DateTime(timezone=True), nullable=False)
    points_awarded = Column(Integer, default=0)
    streak_days_at_activity = Column(Integer, default=0)
    multiplier_at_activity = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    attendance_streak = relationship("AttendanceStreak", back_populates="attendance_logs")

    __table_args__ = (Index("ix_attendance_log_streak_date", "attendance_streak_id", "activity_date"),)

    def __repr__(self):
        return f"<AttendanceLog {self.activity_date}: {self.points_awarded} points>"
