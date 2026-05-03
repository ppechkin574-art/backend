from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class UserQuestionProgress(Base):
    __tablename__ = "user_question_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID, nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    is_correct = Column(Boolean, default=False)
    attempt_type = Column(String, nullable=False)
    attempt_id = Column(Integer, nullable=False)
    solved_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_question", "user_id", "question_id", unique=True),
        Index("idx_user_topic_progress", "user_id", "question_id", "is_correct"),
    )

    question = relationship("Question")
