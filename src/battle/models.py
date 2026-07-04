import uuid
from datetime import datetime

from sqlalchemy import JSON, UUID, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY

from database import Base


class BattleSession(Base):
    __tablename__ = "battle_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player1_id = Column(String, nullable=False, index=True)
    player2_id = Column(String, nullable=True)
    is_bot = Column(Boolean, nullable=False, default=False)
    bot_name = Column(String, nullable=True)
    bot_win_rate = Column(Integer, nullable=True)  # percentage 0-100
    subject_ids = Column(ARRAY(Integer), nullable=False)
    question_data = Column(JSON, nullable=True)  # {questions: [...], correct_answers: {q_id: v_id}}
    status = Column(String, nullable=False, default="searching", index=True)
    # searching | active | finished | abandoned
    winner_id = Column(String, nullable=True)
    player1_score = Column(Integer, nullable=False, default=0)
    player2_score = Column(Integer, nullable=False, default=0)
    stars_player1 = Column(Integer, nullable=False, default=0)
    stars_player2 = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class BattleAnswer(Base):
    __tablename__ = "battle_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("battle_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(String, nullable=False)
    question_id = Column(Integer, nullable=False)
    variant_id = Column(Integer, nullable=True)  # null = timed out
    is_correct = Column(Boolean, nullable=False, default=False)
    answered_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
