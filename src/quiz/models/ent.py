import uuid

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from database import Base
from quiz.dtos.enums import ExamType, Status
from quiz.models.edu_content import Question, Subject, Variant


class EntOption(Base):
    __tablename__ = "ent_options"
    id = Column(Integer, primary_key=True, autoincrement=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    option_number = Column(Integer, nullable=False)
    subject_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)

    subject = relationship(Subject, back_populates="ent_options", passive_deletes=True)
    questions = relationship("EntOptionQuestion", back_populates="ent_option", passive_deletes=True)
    attempts = relationship("EntAttempt", back_populates="options", passive_deletes=True)

    __table_args__ = (UniqueConstraint("subject_id", "option_number", name="ent_options_subject_option_unique"),)


class EntOptionQuestion(Base):
    __tablename__ = "ent_questions"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    ent_option_id = Column(ForeignKey("ent_options.id", ondelete="CASCADE"), nullable=True)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)

    question = relationship(Question, back_populates="ent_options", passive_deletes=True)
    ent_option = relationship(EntOption, back_populates="questions", passive_deletes=True)


class EntAttempt(Base):
    __tablename__ = "ent_attempts"

    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    id = Column(Integer, primary_key=True, autoincrement=True)
    ent_option_id = Column(ForeignKey(EntOption.id, ondelete="SET NULL"))
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    status = Column(Enum(Status), nullable=False)
    score = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    deadline_at = Column(DateTime)
    completed_at = Column(DateTime)
    original_completed_at = Column(DateTime(timezone=True), nullable=True)
    time_correction_applied = Column(Boolean, default=False)
    correction_reason = Column(String, nullable=True)

    # Новые поля для полноценного экзамена
    exam_type = Column(
        Enum(ExamType),
        nullable=False,
        default=ExamType.by_subject,
        server_default="by_subject",
    )
    subject_combination_id = Column(ForeignKey("ent_subject_combinations.id", ondelete="SET NULL"), nullable=True)
    full_exam_question_ids = Column(String, nullable=True)

    # Поле для сохранения текущей позиции в экзамене
    current_question_index = Column(Integer, default=0, nullable=False, server_default="0")

    # Идемпотентная защита начисления баллов в лидерборд: True означает,
    # что баллы уже записаны в user_points для этой попытки.
    # Устанавливается атомарным UPDATE WHERE points_awarded = FALSE,
    # предотвращает двойное начисление при гонке конкурентных запросов.
    points_awarded = Column(Boolean, default=False, nullable=False, server_default="false")

    options = relationship(EntOption, back_populates="attempts", passive_deletes=True)
    subject_combination = relationship(
        "EntSubjectCombination",
        foreign_keys=[subject_combination_id],
        passive_deletes=True,
    )

    @property
    def corrected_spend_time(self) -> int:
        """Скорректированное время в секундах"""
        if self.time_correction_applied and self.original_completed_at:
            return int((self.original_completed_at - self.started_at).total_seconds())
        elif self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return 0

    __table_args__ = (
        Index(
            "idx_unique_active_ent_attempt",
            "student_guid",
            "ent_option_id",
            unique=True,
            postgresql_where=(status == "in_progress"),
        ),
        # Statistics hot paths (/user/statistics/global):
        # overall ENT stats filter (student_guid + exam_type + status==completed).
        Index(
            "ix_ent_attempts_student_examtype_completed",
            "student_guid",
            "exam_type",
            "completed_at",
        ),
        # period ENT stats filter (student_guid + status==completed + completed_at range)
        # — the period helper does NOT filter exam_type, so a status-led index serves it.
        Index(
            "ix_ent_attempts_student_status_completed",
            "student_guid",
            "status",
            "completed_at",
        ),
    )


class EntAttemptAnswer(Base):
    __tablename__ = "ent_attempt_answers"

    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    id = Column(Integer, primary_key=True, autoincrement=True)
    ent_attempt_id = Column(ForeignKey(EntAttempt.id, ondelete="CASCADE"))
    variant_id = Column(
        ForeignKey(Variant.id, ondelete="SET NULL"),
        nullable=True,
    )

    variant = relationship(Variant, passive_deletes=False)
    ent_attempt = relationship(EntAttempt, passive_deletes=False)

    __table_args__ = (
        # FK fan-out: answers are fetched per-attempt in the statistics loop
        # (get_attempt_answers_with_questions) and joined by attempt id in
        # get_attempt_subjects_statistics.
        Index("ix_ent_attempt_answers_attempt", "ent_attempt_id"),
    )


class EntSubjectCombination(Base):
    __tablename__ = "ent_subject_combinations"
    id = Column(Integer, primary_key=True)

    specialized_subject_1_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    specialized_subject_2_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)

    name = Column(String)  # f.e. "Техническое направление", "Гуманитарное направление"
    description = Column(String)  # optional

    specialized_subject_1 = relationship("Subject", foreign_keys=[specialized_subject_1_id], passive_deletes=True)
    specialized_subject_2 = relationship("Subject", foreign_keys=[specialized_subject_2_id], passive_deletes=True)
