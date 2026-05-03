import uuid

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from database import Base
from quiz.dtos.enums import Difficulty, Status


class SubjectModule(Base):
    __tablename__ = "subject_modules"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    subject_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    # image_url = Column(String(500), nullable=True)
    order_index = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    subject = relationship("Subject", back_populates="modules")
    lessons = relationship(
        "ModuleLesson",
        back_populates="module",
        order_by="ModuleLesson.order_index",
        cascade="all, delete-orphan",
    )
    module_test = relationship(
        "ModuleTest",
        back_populates="module",
        uselist=False,
        cascade="all, delete-orphan",
    )
    progress_records = relationship("UserModuleProgress", back_populates="module", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_module_subject_order", "subject_id", "order_index"),
        Index("idx_module_active", "is_active"),
    )


class ModuleLesson(Base):
    __tablename__ = "module_lessons"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    module_id = Column(ForeignKey("subject_modules.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    video_url = Column(String(500), nullable=True)
    presentation_url = Column(String(500), nullable=True)
    # content_html = Column(Text, nullable=True)
    # duration_minutes = Column(Integer, default=0, nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    difficulty = Column(Enum(Difficulty), nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    module = relationship("SubjectModule", back_populates="lessons")
    topic = relationship("Topic", back_populates="module_lessons")
    lesson_test = relationship(
        "LessonTest",
        back_populates="lesson",
        uselist=False,
        cascade="all, delete-orphan",
    )
    progress_records = relationship("UserLessonProgress", back_populates="lesson", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_lesson_module_order", "module_id", "order_index"),
        Index("idx_lesson_published", "is_published"),
        Index("idx_lesson_topic", "topic_id"),
    )


class LessonTest(Base):
    __tablename__ = "lesson_tests"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    lesson_id = Column(ForeignKey("module_lessons.id", ondelete="CASCADE"), nullable=False, unique=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    pass_score_percentage = Column(Integer, default=70, nullable=False)
    time_limit_minutes = Column(Integer, nullable=True)
    max_attempts = Column(Integer, default=3, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    lesson = relationship("ModuleLesson", back_populates="lesson_test")
    questions = relationship("LessonTestQuestion", back_populates="lesson_test", cascade="all, delete-orphan")
    attempts = relationship("LessonTestAttempt", back_populates="lesson_test", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_lesson_test_active", "is_active"),)


class ModuleTest(Base):
    __tablename__ = "module_tests"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    module_id = Column(
        ForeignKey("subject_modules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    pass_score_percentage = Column(Integer, default=70, nullable=False)
    time_limit_minutes = Column(Integer, nullable=True)
    max_attempts = Column(Integer, default=3, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    module = relationship("SubjectModule", back_populates="module_test")
    questions = relationship("ModuleTestQuestion", back_populates="module_test", cascade="all, delete-orphan")
    attempts = relationship("ModuleTestAttempt", back_populates="module_test", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_module_test_active", "is_active"),)


class LessonTestQuestion(Base):
    __tablename__ = "lesson_test_questions"

    id = Column(Integer, primary_key=True)
    lesson_test_id = Column(ForeignKey("lesson_tests.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    points = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    lesson_test = relationship("LessonTest", back_populates="questions")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("lesson_test_id", "question_id", name="uq_lesson_test_question"),
        Index("idx_lesson_test_question_order", "lesson_test_id", "order_index"),
    )


class ModuleTestQuestion(Base):
    __tablename__ = "module_test_questions"

    id = Column(Integer, primary_key=True)
    module_test_id = Column(ForeignKey("module_tests.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    points = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    module_test = relationship("ModuleTest", back_populates="questions")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("module_test_id", "question_id", name="uq_module_test_question"),
        Index("idx_module_test_question_order", "module_test_id", "order_index"),
    )


class UserLessonProgress(Base):
    __tablename__ = "user_lesson_progress"

    id = Column(Integer, primary_key=True)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    lesson_id = Column(ForeignKey("module_lessons.id", ondelete="CASCADE"), nullable=False)

    watched_video = Column(Boolean, default=False, nullable=False)
    viewed_presentation = Column(Boolean, default=False, nullable=False)
    read_content = Column(Boolean, default=False, nullable=False)

    completed_test = Column(Boolean, default=False, nullable=False)
    test_score = Column(Integer, default=0, nullable=False)
    test_max_score = Column(Integer, default=0, nullable=False)
    test_percentage = Column(Float, default=0.0, nullable=False)
    test_attempts_count = Column(Integer, default=0, nullable=False)

    time_spent_seconds = Column(Integer, default=0, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    last_accessed_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    lesson = relationship("ModuleLesson", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("student_guid", "lesson_id", name="uq_user_lesson"),
        Index("idx_user_lesson_progress", "student_guid", "lesson_id"),
        Index("idx_user_lesson_completed", "student_guid", "is_completed"),
        Index("idx_lesson_progress", "lesson_id", "is_completed"),
    )


class UserModuleProgress(Base):
    __tablename__ = "user_module_progress"

    id = Column(Integer, primary_key=True)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    module_id = Column(ForeignKey("subject_modules.id", ondelete="CASCADE"), nullable=False)

    completed_lessons_count = Column(Integer, default=0, nullable=False)
    total_lessons_count = Column(Integer, default=0, nullable=False)

    module_test_completed = Column(Boolean, default=False, nullable=False)
    module_test_score = Column(Integer, default=0, nullable=False)
    module_test_max_score = Column(Integer, default=0, nullable=False)
    module_test_percentage = Column(Float, default=0.0, nullable=False)
    module_test_attempts_count = Column(Integer, default=0, nullable=False)

    is_completed = Column(Boolean, default=False, nullable=False)
    overall_progress_percentage = Column(Float, default=0.0, nullable=False)
    time_spent_seconds = Column(Integer, default=0, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    module = relationship("SubjectModule", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("student_guid", "module_id", name="uq_user_module"),
        Index("idx_user_module_progress", "student_guid", "module_id"),
        Index("idx_user_module_completed", "student_guid", "is_completed"),
        Index("idx_module_progress", "module_id", "is_completed"),
    )


class LessonTestAttempt(Base):
    __tablename__ = "lesson_test_attempts"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    lesson_test_id = Column(ForeignKey("lesson_tests.id", ondelete="CASCADE"), nullable=False)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    attempt_number = Column(Integer, default=1, nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.in_progress)
    score = Column(Integer, default=0, nullable=False)
    max_score = Column(Integer, default=0, nullable=False)
    percentage = Column(Float, default=0.0, nullable=False)
    is_passed = Column(Boolean, default=False, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    time_spent_seconds = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    lesson_test = relationship("LessonTest", back_populates="attempts")
    answers = relationship("LessonTestAnswer", back_populates="attempt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_lesson_test_attempt_student", "student_guid", "lesson_test_id"),
        Index("idx_lesson_test_attempt_status", "status"),
    )


class ModuleTestAttempt(Base):
    __tablename__ = "module_test_attempts"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    module_test_id = Column(ForeignKey("module_tests.id", ondelete="CASCADE"), nullable=False)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    attempt_number = Column(Integer, default=1, nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.in_progress)
    score = Column(Integer, default=0, nullable=False)
    max_score = Column(Integer, default=0, nullable=False)
    percentage = Column(Float, default=0.0, nullable=False)
    is_passed = Column(Boolean, default=False, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    time_spent_seconds = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    module_test = relationship("ModuleTest", back_populates="attempts")
    answers = relationship("ModuleTestAnswer", back_populates="attempt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_module_test_attempt_student", "student_guid", "module_test_id"),
        Index("idx_module_test_attempt_status", "status"),
    )


class LessonTestAnswer(Base):
    __tablename__ = "lesson_test_answers"

    id = Column(Integer, primary_key=True)
    lesson_test_attempt_id = Column(ForeignKey("lesson_test_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(ForeignKey("variants.id", ondelete="SET NULL"), nullable=True)
    is_correct = Column(Boolean, default=False, nullable=False)
    points_earned = Column(Integer, default=0, nullable=False)
    answered_at = Column(DateTime, server_default=func.now(), nullable=False)

    attempt = relationship("LessonTestAttempt", back_populates="answers")
    question = relationship("Question")
    variant = relationship("Variant")

    __table_args__ = (
        Index("idx_lesson_test_answer_attempt", "lesson_test_attempt_id"),
        Index("idx_lesson_test_answer_question", "question_id"),
    )


class ModuleTestAnswer(Base):
    __tablename__ = "module_test_answers"

    id = Column(Integer, primary_key=True)
    module_test_attempt_id = Column(ForeignKey("module_test_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(ForeignKey("variants.id", ondelete="SET NULL"), nullable=True)
    is_correct = Column(Boolean, default=False, nullable=False)
    points_earned = Column(Integer, default=0, nullable=False)
    answered_at = Column(DateTime, server_default=func.now(), nullable=False)

    attempt = relationship("ModuleTestAttempt", back_populates="answers")
    question = relationship("Question")
    variant = relationship("Variant")

    __table_args__ = (
        Index("idx_module_test_answer_attempt", "module_test_attempt_id"),
        Index("idx_module_test_answer_question", "question_id"),
    )
