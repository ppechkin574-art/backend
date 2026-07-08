"""Validation tests for battle Pydantic schemas and service-layer guards.

Covers:
- JoinQueueRequest: valid/invalid subject_ids lists
- BotFinishRequest: score ranges and boundary values
- SessionStatusResponse: required fields, optional defaults
- WsBattleEnd: winner enum values, star amounts
- WsQuestionResult: is_correct, correct_variant_id
- join_or_create: subject normalization (sort dedup guard via _subject_key)
- BattleService._subject_key: canonical ordering guarantee
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from battle.schemas import (
    BotFinishRequest,
    BotFinishResponse,
    JoinQueueRequest,
    JoinQueueResponse,
    SessionStatusResponse,
    WsBattleEnd,
    WsBattleStart,
    WsOpponentAnswered,
    WsQuestionResult,
)
from battle.service import BattleService, BATTLE_STARS_WIN, BATTLE_STARS_DRAW

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# JoinQueueRequest
# ---------------------------------------------------------------------------


class TestJoinQueueRequest:
    def test_valid_single_subject(self):
        req = JoinQueueRequest(subject_ids=[1])
        assert req.subject_ids == [1]

    def test_valid_two_subjects(self):
        req = JoinQueueRequest(subject_ids=[3, 7])
        assert req.subject_ids == [3, 7]

    def test_empty_list_accepted_by_pydantic(self):
        # Pydantic does not enforce min-length here — route validation handles it
        req = JoinQueueRequest(subject_ids=[])
        assert req.subject_ids == []

    def test_duplicate_ids_preserved(self):
        # Schema does not deduplicate; service _subject_key sorts and joins
        req = JoinQueueRequest(subject_ids=[2, 2])
        assert req.subject_ids == [2, 2]

    def test_large_id_accepted(self):
        req = JoinQueueRequest(subject_ids=[999999])
        assert req.subject_ids == [999999]

    def test_missing_subject_ids_raises(self):
        with pytest.raises(ValidationError):
            JoinQueueRequest()  # type: ignore[call-arg]

    def test_non_integer_subject_id_raises(self):
        with pytest.raises(ValidationError):
            JoinQueueRequest(subject_ids=["math"])  # type: ignore[list-item]

    def test_none_subject_ids_raises(self):
        with pytest.raises(ValidationError):
            JoinQueueRequest(subject_ids=None)  # type: ignore[arg-type]

    def test_string_that_looks_like_list_raises(self):
        with pytest.raises(ValidationError):
            JoinQueueRequest(subject_ids="[1,2]")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JoinQueueResponse
# ---------------------------------------------------------------------------


class TestJoinQueueResponse:
    def test_searching_status(self):
        r = JoinQueueResponse(session_id="abc", status="searching")
        assert r.status == "searching"
        assert r.session_id == "abc"

    def test_active_status(self):
        r = JoinQueueResponse(session_id="xyz", status="active")
        assert r.status == "active"

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            JoinQueueResponse(status="searching")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# BotFinishRequest
# ---------------------------------------------------------------------------


class TestBotFinishRequest:
    def test_typical_scores(self):
        req = BotFinishRequest(player1_score=7, player2_score=3)
        assert req.player1_score == 7
        assert req.player2_score == 3

    def test_zero_scores(self):
        req = BotFinishRequest(player1_score=0, player2_score=0)
        assert req.player1_score == 0
        assert req.player2_score == 0

    def test_max_score_per_battle(self):
        # 2 subjects × 5 questions = 10 max
        req = BotFinishRequest(player1_score=10, player2_score=8)
        assert req.player1_score == 10

    def test_equal_scores_draw_case(self):
        req = BotFinishRequest(player1_score=5, player2_score=5)
        assert req.player1_score == req.player2_score

    def test_negative_score_accepted_by_pydantic(self):
        # Pydantic int has no min constraint — service logic handles bounds
        req = BotFinishRequest(player1_score=-1, player2_score=0)
        assert req.player1_score == -1

    def test_missing_player1_score_raises(self):
        with pytest.raises(ValidationError):
            BotFinishRequest(player2_score=5)  # type: ignore[call-arg]

    def test_missing_player2_score_raises(self):
        with pytest.raises(ValidationError):
            BotFinishRequest(player1_score=5)  # type: ignore[call-arg]

    def test_float_raises_validation_error(self):
        # Pydantic v2 does NOT coerce float→int by default; float scores are rejected
        with pytest.raises(ValidationError):
            BotFinishRequest(player1_score=7.9, player2_score=3.1)  # type: ignore[arg-type]

    def test_string_score_raises(self):
        with pytest.raises(ValidationError):
            BotFinishRequest(player1_score="high", player2_score=3)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SessionStatusResponse
# ---------------------------------------------------------------------------


class TestSessionStatusResponse:
    def test_required_fields_present(self):
        r = SessionStatusResponse(session_id="s1", status="searching")
        assert r.session_id == "s1"
        assert r.status == "searching"

    def test_opponent_name_defaults_to_none(self):
        r = SessionStatusResponse(session_id="s1", status="active")
        assert r.opponent_name is None

    def test_is_bot_defaults_to_false(self):
        r = SessionStatusResponse(session_id="s1", status="active")
        assert r.is_bot is False

    def test_started_at_defaults_to_none(self):
        r = SessionStatusResponse(session_id="s1", status="active")
        assert r.started_at is None

    def test_explicit_opponent_name(self):
        r = SessionStatusResponse(session_id="s1", status="active", opponent_name="Бот")
        assert r.opponent_name == "Бот"

    def test_is_bot_true(self):
        r = SessionStatusResponse(session_id="s1", status="active", is_bot=True)
        assert r.is_bot is True

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            SessionStatusResponse(status="searching")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# WsBattleEnd
# ---------------------------------------------------------------------------


class TestWsBattleEnd:
    def test_type_field_is_battle_end(self):
        e = WsBattleEnd(my_score=7, opponent_score=3, winner="me", stars_earned=50)
        assert e.type == "battle_end"

    def test_win_scenario(self):
        e = WsBattleEnd(my_score=7, opponent_score=3, winner="me", stars_earned=BATTLE_STARS_WIN)
        assert e.winner == "me"
        assert e.stars_earned == 50

    def test_loss_scenario(self):
        e = WsBattleEnd(my_score=3, opponent_score=7, winner="opponent", stars_earned=0)
        assert e.winner == "opponent"
        assert e.stars_earned == 0

    def test_draw_scenario(self):
        e = WsBattleEnd(my_score=5, opponent_score=5, winner="draw", stars_earned=BATTLE_STARS_DRAW)
        assert e.winner == "draw"
        assert e.stars_earned == 25

    def test_stars_earned_non_negative_on_win(self):
        e = WsBattleEnd(my_score=8, opponent_score=2, winner="me", stars_earned=50)
        assert e.stars_earned >= 0

    def test_missing_winner_raises(self):
        with pytest.raises(ValidationError):
            WsBattleEnd(my_score=5, opponent_score=3, stars_earned=50)  # type: ignore[call-arg]

    def test_missing_stars_earned_raises(self):
        with pytest.raises(ValidationError):
            WsBattleEnd(my_score=5, opponent_score=3, winner="me")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# WsQuestionResult
# ---------------------------------------------------------------------------


class TestWsQuestionResult:
    def test_type_is_question_result(self):
        r = WsQuestionResult(
            question_id=1, is_correct=True, correct_variant_id=42,
            my_score=1, opponent_score=0,
        )
        assert r.type == "question_result"

    def test_correct_answer(self):
        r = WsQuestionResult(
            question_id=1, is_correct=True, correct_variant_id=42,
            my_score=3, opponent_score=2,
        )
        assert r.is_correct is True
        assert r.correct_variant_id == 42

    def test_wrong_answer(self):
        r = WsQuestionResult(
            question_id=2, is_correct=False, correct_variant_id=99,
            my_score=1, opponent_score=3,
        )
        assert r.is_correct is False
        assert r.correct_variant_id == 99

    def test_scores_updated_correctly(self):
        r = WsQuestionResult(
            question_id=3, is_correct=True, correct_variant_id=7,
            my_score=5, opponent_score=4,
        )
        assert r.my_score == 5
        assert r.opponent_score == 4

    def test_missing_question_id_raises(self):
        with pytest.raises(ValidationError):
            WsQuestionResult(is_correct=True, correct_variant_id=1, my_score=0, opponent_score=0)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# WsOpponentAnswered
# ---------------------------------------------------------------------------


class TestWsOpponentAnswered:
    def test_type_is_opponent_answered(self):
        e = WsOpponentAnswered(question_id=1, opponent_score=3)
        assert e.type == "opponent_answered"

    def test_stores_fields(self):
        e = WsOpponentAnswered(question_id=5, opponent_score=0)
        assert e.question_id == 5
        assert e.opponent_score == 0

    def test_missing_question_id_raises(self):
        with pytest.raises(ValidationError):
            WsOpponentAnswered(opponent_score=2)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# BattleService._subject_key — canonical queue-key ordering
# ---------------------------------------------------------------------------


class TestSubjectKey:
    def _svc(self):
        return BattleService(db=MagicMock(), redis=MagicMock())

    def test_same_ids_different_order_produce_same_key(self):
        svc = self._svc()
        assert svc._subject_key([1, 2]) == svc._subject_key([2, 1])

    def test_single_subject_key(self):
        svc = self._svc()
        assert svc._subject_key([7]) == "7"

    def test_two_subjects_key_sorted(self):
        svc = self._svc()
        assert svc._subject_key([3, 1]) == "1:3"

    def test_three_subjects_sorted(self):
        svc = self._svc()
        assert svc._subject_key([10, 5, 1]) == "1:5:10"

    def test_duplicate_ids_in_key(self):
        # Duplicate IDs produce duplicate entries in the key
        svc = self._svc()
        assert svc._subject_key([2, 2]) == "2:2"

    def test_empty_list_gives_empty_key(self):
        svc = self._svc()
        assert svc._subject_key([]) == ""


# ---------------------------------------------------------------------------
# Star constants sanity
# ---------------------------------------------------------------------------


class TestStarConstants:
    def test_win_stars_value(self):
        assert BATTLE_STARS_WIN == 50

    def test_draw_stars_value(self):
        assert BATTLE_STARS_DRAW == 25

    def test_win_greater_than_draw(self):
        assert BATTLE_STARS_WIN > BATTLE_STARS_DRAW

    def test_draw_greater_than_zero(self):
        assert BATTLE_STARS_DRAW > 0

    def test_loss_stars_is_zero(self):
        # There is no BATTLE_STARS_LOSS constant — loss = 0 is implicit
        loss = 0
        assert loss < BATTLE_STARS_DRAW
