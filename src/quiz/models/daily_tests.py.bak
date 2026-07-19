import uuid

from sqlalchemy import (
    UUID,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from database import Base
from quiz.models.edu_content import Question, Subject, Variant


class DailyTestSubjectPreference(Base):
    """Выбранные предметы пользователя для ежедневных тестов"""

    __tablename__ = "daily_test_subject_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_guid = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    subject = relationship("Subject", foreign_keys=[subject_id])

    __table_args__ = (
        UniqueConstraint("student_guid", "subject_id", name="uq_student_subject_preference"),
        Index("idx_daily_subject_prefs_student", "student_guid"),
    )


class DailyTestAttempt(Base):
    """Попытка прохождения ежедневного теста"""

    __tablename__ = "daily_test_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    student_guid = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    test_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="in_progress")
    score = Column(Integer, default=0, nullable=False)
    correct_answers = Column(Integer, default=0, nullable=False)
    incorrect_answers = Column(Integer, default=0, nullable=False)
    skipped_answers = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    questions = relationship("DailyTestAttemptQuestion", back_populates="attempt", cascade="all, delete-orphan")
    answers = relationship("DailyTestAnswer", back_populates="attempt", cascade="all, delete-orphan")
    subject = relationship(Subject)

    __table_args__ = (
        Index("idx_daily_attempts_student", "student_guid"),
        Index("idx_daily_attempts_date", "test_date"),
        Index("idx_daily_attempts_subject", "subject_id"),
        # Statistics hot path: period + overall daily stats filter
        # student_guid + status=='completed' (+ completed_at range for period).
        # The existing student-only index can't satisfy the status/range predicate.
        Index(
            "ix_daily_attempts_student_status_completed",
            "student_guid",
            "status",
            "completed_at",
        ),
    )


class DailyTestAttemptQuestion(Base):
    """Вопросы в попытке ежедневного теста (для сохранения истории)"""

    __tablename__ = "daily_test_attempt_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    daily_test_attempt_id = Column(Integer, ForeignKey("daily_test_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    order_number = Column(Integer, nullable=False)

    # Relationships
    attempt = relationship("DailyTestAttempt", back_populates="questions")
    question = relationship(Question)

    __table_args__ = (Index("idx_daily_attempt_questions_attempt", "daily_test_attempt_id"),)


class DailyTestAnswer(Base):
    """Ответы пользователя на вопросы ежедневного теста"""

    __tablename__ = "daily_test_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    daily_test_attempt_id = Column(Integer, ForeignKey("daily_test_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(Integer, ForeignKey("variants.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    attempt = relationship("DailyTestAttempt", back_populates="answers")
    question = relationship(Question)
    variant = relationship(Variant)

    __table_args__ = (Index("idx_daily_answers_attempt", "daily_test_attempt_id"),)


class DailyTestDeviceToken(Base):
    """FCM токены устройств для уведомлений о ежедневных тестах"""

    __tablename__ = "daily_test_device_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_guid = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(512), nullable=False, unique=True)
    platform = Column(String(50), nullable=True)
    device_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("idx_daily_test_device_tokens_student", "student_guid"),)


class DailyNotificationTemplate(Base):
    """Singleton settings row for the daily push notification scheduler.

    One row (id=1, CHECK enforced). Admin edits title/body/hour/minute/timezone
    from the push notifications page; the scheduler re-reads this row on every
    tick so changes propagate within a day without a redeploy.
    """

    __tablename__ = "daily_notification_template"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, server_default="true")
    title = Column(String(200), nullable=False)
    body = Column(String(500), nullable=False)
    hour = Column(Integer, nullable=False, server_default="9")
    minute = Column(Integer, nullable=False, server_default="0")
    timezone = Column(String(64), nullable=False, server_default="Asia/Almaty")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_daily_notification_template_singleton"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="ck_daily_notification_template_hour"),
        CheckConstraint("minute BETWEEN 0 AND 59", name="ck_daily_notification_template_minute"),
    )
