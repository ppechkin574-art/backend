from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from database import Base


class CashbackUserState(Base):
    __tablename__ = "cashback_user_states"

    id = Column(Integer, primary_key=True)
    student_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    current_streak_number = Column(Integer, default=1, nullable=False)
    current_day_in_streak = Column(Integer, default=0, nullable=False)
    total_streaks_completed = Column(Integer, default=0, nullable=False)
    total_cashback_earned = Column(Integer, default=0, nullable=False)
    last_completed_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student = relationship("Student")

    def __repr__(self):
        return f"<CashbackUserState student={self.student_guid} streak={self.current_streak_number} day={self.current_day_in_streak}>"


class CashbackDailyCompletion(Base):
    __tablename__ = "cashback_daily_completions"

    id = Column(Integer, primary_key=True)
    student_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    completion_date = Column(Date, nullable=False)
    streak_number = Column(Integer, nullable=False)
    day_number = Column(Integer, nullable=False)
    reward_earned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("student_guid", "completion_date", name="uq_cashback_daily_student_date"),
        Index("ix_cashback_daily_student_date", "student_guid", "completion_date"),
    )

    def __repr__(self):
        return f"<CashbackDailyCompletion student={self.student_guid} date={self.completion_date} streak={self.streak_number} day={self.day_number}>"


class CashbackRewardHistory(Base):
    __tablename__ = "cashback_reward_history"

    id = Column(Integer, primary_key=True)
    student_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = Column(Integer, nullable=False)
    awarded_at = Column(DateTime(timezone=True), server_default=func.now())
    streak_number = Column(Integer, nullable=False)

    def __repr__(self):
        return f"<CashbackRewardHistory student={self.student_guid} amount={self.amount} streak={self.streak_number}>"
