from __future__ import annotations

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
    func,
)
from sqlalchemy.orm import relationship

from database import Base
from quiz.dtos.enums import Status


class Trainer(Base):
    __tablename__ = "trainers"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    name = Column(String)
    topic_id = Column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)

    topic = relationship("Topic", back_populates="trainers", passive_deletes=True)
    trainer_questions = relationship("TrainerQuestion", back_populates="trainers", passive_deletes=True)
    attempts = relationship("TrainerAttempt", back_populates="trainer", passive_deletes=True)


class TrainerQuestion(Base):
    __tablename__ = "trainer_questions"
    id = Column(Integer, primary_key=True)
    trainer_id = Column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)

    question = relationship("Question", back_populates="trainer_questions", passive_deletes=True)
    trainers = relationship("Trainer", back_populates="trainer_questions", passive_deletes=True)


class TrainerAttempt(Base):
    __tablename__ = "trainer_attempts"
    id = Column(Integer, primary_key=True)
    trainer_id = Column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    status = Column(Enum(Status), nullable=False)
    score = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime)
    active_time_seconds = Column(Integer, default=0)  # Сумма активного времени вопросов
    time_correction_applied = Column(Boolean, default=False)

    trainer = relationship(Trainer, back_populates="attempts", passive_deletes=True)
    questions = relationship("TrainerAttemptQuestion", back_populates="trainer_attempt", passive_deletes=True)

    __table_args__ = (
        # Statistics hot path: period + overall trainer stats both filter
        # student_guid + status==completed (+ completed_at range for period).
        Index(
            "ix_trainer_attempts_student_status_completed",
            "student_guid",
            "status",
            "completed_at",
        ),
    )


class TrainerAttemptQuestion(Base):
    __tablename__ = "trainer_attempt_questions"
    id = Column(Integer, primary_key=True)
    trainer_attempt_id = Column(ForeignKey("trainer_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(ForeignKey("questions.id", ondelete="SET NULL"))
    spend_time = Column(Integer, nullable=False, default=0)

    trainer_attempt = relationship(TrainerAttempt, back_populates="questions", passive_deletes=True)
    question = relationship("Question", back_populates="trainer_attempt_questions", passive_deletes=True)
    answers = relationship("TrainerAttemptAnswer", back_populates="attempt_question", passive_deletes=True)

    __table_args__ = (
        # FK fan-out: questions loaded per-attempt (relationship) and joined by
        # attempt id in get_overall_subject/topic_progress.
        Index("ix_trainer_attempt_questions_attempt", "trainer_attempt_id"),
    )


class TrainerAttemptAnswer(Base):
    __tablename__ = "trainer_attempt_answers"
    id = Column(Integer, primary_key=True)
    trainer_attempt_question_id = Column(ForeignKey("trainer_attempt_questions.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(ForeignKey("variants.id", ondelete="CASCADE"), nullable=False)
    student_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    attempt_question = relationship(TrainerAttemptQuestion, back_populates="answers", passive_deletes=True)
    variant = relationship("Variant", passive_deletes=True)

    __table_args__ = (
        # FK fan-out: answers joined by trainer_attempt_question_id in
        # get_overall_subject/topic_progress.
        Index("ix_trainer_attempt_answers_question", "trainer_attempt_question_id"),
    )
