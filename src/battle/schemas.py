from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JoinQueueRequest(BaseModel):
    subject_ids: list[int]


class JoinQueueResponse(BaseModel):
    session_id: str
    status: str  # "searching" | "active"


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    opponent_name: str | None = None
    is_bot: bool = False
    started_at: datetime | None = None


class BattleVariant(BaseModel):
    id: int
    text: str


class BattleQuestion(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    text: str
    variants: list[BattleVariant]
    explanation: str | None = None
    image_url: str | None = None


class BattleOpponent(BaseModel):
    name: str
    is_bot: bool = False  # always False sent to client


class WsBattleStart(BaseModel):
    type: str = "battle_start"
    session_id: str
    total_time: int = 300
    questions: list[BattleQuestion]
    opponent: BattleOpponent
    my_score: int = 0
    opponent_score: int = 0


class WsQuestionResult(BaseModel):
    type: str = "question_result"
    question_id: int
    is_correct: bool
    correct_variant_id: int
    my_score: int
    opponent_score: int


class WsOpponentAnswered(BaseModel):
    type: str = "opponent_answered"
    question_id: int
    opponent_score: int


class WsBattleEnd(BaseModel):
    type: str = "battle_end"
    my_score: int
    opponent_score: int
    winner: str  # "me" | "opponent" | "draw"
    stars_earned: int


class WsOvertimeStart(BaseModel):
    type: str = "overtime_start"
    extra_questions: list[BattleQuestion]
    total_time: int = 150


class WsOpponentDisconnected(BaseModel):
    type: str = "opponent_disconnected"


class WsBattleForfeit(BaseModel):
    type: str = "battle_forfeit"
    forfeited_by: str  # "opponent"


class WsError(BaseModel):
    type: str = "error"
    message: str


class DailyLeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    stars_today: int
    wins: int
    losses: int


class DailyLeaderboardResponse(BaseModel):
    date: str
    entries: list[DailyLeaderboardEntry]
    my_entry: DailyLeaderboardEntry | None = None


class BotFinishRequest(BaseModel):
    player1_score: int
    player2_score: int


class BotFinishResponse(BaseModel):
    stars_earned: int
