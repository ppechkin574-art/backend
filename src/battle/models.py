import uuid
from datetime import datetime

from sqlalchemy import JSON, UUID, Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY

from database import Base


class BattleSettings(Base):
    """Single-row, admin-editable battle tuning (mirrors
    leaderboard_points_settings). Values that used to be hardcoded constants
    in battle/service.py live here so they can be changed from the admin panel
    without a redeploy. A missing row → code defaults."""

    __tablename__ = "battle_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Stars credited by outcome.
    stars_win = Column(Integer, nullable=False, server_default="50")
    stars_draw = Column(Integer, nullable=False, server_default="25")
    stars_loss = Column(Integer, nullable=False, server_default="0")
    # Battle format.
    questions_per_subject = Column(Integer, nullable=False, server_default="5")
    time_seconds = Column(Integer, nullable=False, server_default="300")
    # Bot difficulty — the win-rate is picked uniformly in [min, max].
    bot_win_rate_min = Column(Integer, nullable=False, server_default="50")
    bot_win_rate_max = Column(Integer, nullable=False, server_default="62")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


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
