"""Unit tests for BattleService.

Tests cover:
- record_answer: correct / wrong / score tracking / db commit
- all_answered: both complete / partial / empty questions
- finish_session: win / loss / draw → correct stars and status
- forfeit: winner assignment and noop on finished sessions
- questions_for_client: explanation present, correct_variant_id stripped
- build_correct_answers: correct ID mapping

All tests are pure — no DB, no network.
DB and Redis are mocked via MagicMock.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import battle.models  # noqa: F401 — registers ORM mapper so BattleAnswer() can be instantiated

import bank.models  # noqa: F401 — registers bank ORM mapper so Transaction() can be instantiated

from battle.service import (
    BATTLE_STARS_DRAW,
    BATTLE_STARS_WIN,
    BattleService,
    build_correct_answers,
    questions_for_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc(db=None, redis=None):
    return BattleService(db=db or MagicMock(), redis=redis or MagicMock())


def _make_session(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        player1_id="user-1",
        player2_id="bot:Айгерім Н.",
        player1_score=0,
        player2_score=0,
        status="active",
        is_bot=True,
        bot_name="Айгерім Н.",
        winner_id=None,
        stars_player1=0,
        stars_player2=0,
        question_data={
            "questions": [{"id": 1}, {"id": 2}],
            "correct_answers": {"1": 10, "2": 20},
        },
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_answer(player_id: str, question_id: int):
    return SimpleNamespace(player_id=player_id, question_id=question_id)


# ---------------------------------------------------------------------------
# record_answer
# ---------------------------------------------------------------------------


def _db_no_prior_answer():
    """Return a MagicMock db where filter_by(...).first() returns None (no duplicate)."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    return db


class TestRecordAnswer:
    def test_correct_answer_by_player1_increments_player1_score(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        is_correct, correct_vid = svc.record_answer(session, "user-1", 1, 10)

        assert is_correct is True
        assert correct_vid == 10
        assert session.player1_score == 1
        assert session.player2_score == 0

    def test_correct_answer_by_player2_increments_player2_score(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        is_correct, _ = svc.record_answer(session, "bot:Айгерім Н.", 1, 10)

        assert is_correct is True
        assert session.player2_score == 1
        assert session.player1_score == 0

    def test_wrong_answer_does_not_change_score(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        is_correct, correct_vid = svc.record_answer(session, "user-1", 1, 99)

        assert is_correct is False
        assert correct_vid == 10  # still returns correct variant
        assert session.player1_score == 0

    def test_unknown_question_id_treated_as_wrong(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        is_correct, correct_vid = svc.record_answer(session, "user-1", 999, 10)

        assert is_correct is False
        assert correct_vid == 0

    def test_none_variant_id_is_wrong(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        is_correct, _ = svc.record_answer(session, "user-1", 1, None)

        assert is_correct is False
        assert session.player1_score == 0

    def test_adds_answer_to_db_and_commits(self):
        db = _db_no_prior_answer()
        session = _make_session()
        svc = _make_svc(db=db)

        svc.record_answer(session, "user-1", 1, 10)

        db.add.assert_called_once()
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# all_answered
# ---------------------------------------------------------------------------


class TestAllAnswered:
    def _set_answers(self, db, answers):
        db.query.return_value.filter.return_value.all.return_value = answers

    def test_true_when_both_players_answered_all_questions(self):
        db = MagicMock()
        session = _make_session()
        self._set_answers(db, [
            _make_answer("user-1", 1),
            _make_answer("user-1", 2),
            _make_answer("bot:Айгерім Н.", 1),
            _make_answer("bot:Айгерім Н.", 2),
        ])
        assert _make_svc(db=db).all_answered(session) is True

    def test_false_when_player1_missing_one_answer(self):
        db = MagicMock()
        session = _make_session()
        self._set_answers(db, [
            _make_answer("user-1", 1),           # only 1 of 2
            _make_answer("bot:Айгерім Н.", 1),
            _make_answer("bot:Айгерім Н.", 2),
        ])
        assert _make_svc(db=db).all_answered(session) is False

    def test_false_when_bot_has_not_answered_anything(self):
        db = MagicMock()
        session = _make_session()
        self._set_answers(db, [
            _make_answer("user-1", 1),
            _make_answer("user-1", 2),
        ])
        assert _make_svc(db=db).all_answered(session) is False

    def test_true_when_no_questions_exist(self):
        db = MagicMock()
        session = _make_session(question_data={"questions": [], "correct_answers": {}})
        self._set_answers(db, [])
        assert _make_svc(db=db).all_answered(session) is True


# ---------------------------------------------------------------------------
# finish_session
# ---------------------------------------------------------------------------


class TestFinishSession:
    def test_player1_wins_gets_battle_stars_win(self):
        db = MagicMock()
        session = _make_session(player1_score=7, player2_score=5)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        assert session.winner_id == "user-1"
        assert session.stars_player1 == BATTLE_STARS_WIN
        assert session.stars_player2 == 0

    def test_player2_wins_player1_gets_zero_stars(self):
        db = MagicMock()
        session = _make_session(player1_score=3, player2_score=8)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        assert session.winner_id == "bot:Айгерім Н."
        assert session.stars_player1 == 0
        assert session.stars_player2 == BATTLE_STARS_WIN

    def test_draw_gives_draw_stars_to_player1(self):
        db = MagicMock()
        session = _make_session(player1_score=5, player2_score=5)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        assert session.winner_id == "draw"
        assert session.stars_player1 == BATTLE_STARS_DRAW
        assert session.stars_player2 == BATTLE_STARS_DRAW

    def test_sets_status_to_finished_and_records_timestamp(self):
        db = MagicMock()
        session = _make_session(player1_score=1, player2_score=0)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        assert session.status == "finished"
        assert session.finished_at is not None

    def test_commits_once(self):
        db = MagicMock()
        session = _make_session(player1_score=1, player2_score=0)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        db.commit.assert_called_once()

    def test_win_increments_leaderboard_via_redis(self):
        db = MagicMock()
        redis = MagicMock()
        session = _make_session(player1_score=5, player2_score=4)
        svc = _make_svc(db=db, redis=redis)

        svc.finish_session(session)

        redis.zincrby.assert_called_once()
        # second arg is the score delta — must be BATTLE_STARS_WIN
        _, stars, _ = redis.zincrby.call_args[0]
        assert stars == BATTLE_STARS_WIN

    def test_draw_increments_losses_not_wins_in_leaderboard(self):
        db = MagicMock()
        redis = MagicMock()
        session = _make_session(player1_score=4, player2_score=4)
        svc = _make_svc(db=db, redis=redis)

        svc.finish_session(session)

        # Draw → won=False → losses key incremented, wins key NOT incremented
        called_keys = [call[0][0] for call in redis.hincrby.call_args_list]
        assert any("losses" in k for k in called_keys)
        assert not any("wins" in k for k in called_keys)


# ---------------------------------------------------------------------------
# finish_session — bank crediting
# ---------------------------------------------------------------------------

# A proper UUID string is required so uuid.UUID() succeeds inside _credit_stars_to_bank
_REAL_PLAYER_UUID = "550e8400-e29b-41d4-a716-446655440000"


class TestFinishSessionBankCredit:
    def test_win_adds_transaction_to_db(self):
        db = MagicMock()
        session = _make_session(player1_score=5, player2_score=3, player1_id=_REAL_PLAYER_UUID)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        # A Transaction record must be added for the winner's balance credit
        db.add.assert_called_once()

    def test_loss_does_not_add_transaction(self):
        db = MagicMock()
        session = _make_session(player1_score=2, player2_score=5, player1_id=_REAL_PLAYER_UUID)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        # player1 lost → stars_player1 = 0 → no bank transaction
        db.add.assert_not_called()

    def test_draw_adds_transaction_to_db(self):
        db = MagicMock()
        session = _make_session(player1_score=4, player2_score=4, player1_id=_REAL_PLAYER_UUID)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        # Draw gives BATTLE_STARS_DRAW → Transaction added
        db.add.assert_called_once()

    def test_bot_player1_id_skips_bank_credit(self):
        db = MagicMock()
        session = _make_session(player1_score=5, player2_score=3, player1_id="bot:Айгерім Н.")
        svc = _make_svc(db=db)

        svc.finish_session(session)

        # "bot:..." is not a valid UUID → credit is skipped
        db.add.assert_not_called()

    def test_no_bank_account_skips_credit(self):
        db = MagicMock()
        # Return None for the account query to simulate no account
        db.query.return_value.filter.return_value.first.return_value = None
        session = _make_session(player1_score=5, player2_score=3, player1_id=_REAL_PLAYER_UUID)
        svc = _make_svc(db=db)

        svc.finish_session(session)

        # Account not found → add never called
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# forfeit
# ---------------------------------------------------------------------------


class TestForfeit:
    def test_player1_forfeits_makes_opponent_winner(self):
        db = MagicMock()
        session = _make_session()
        svc = _make_svc(db=db)

        svc.forfeit(session, "user-1")

        assert session.winner_id == "bot:Айгерім Н."
        assert session.stars_player1 == 0
        assert session.stars_player2 == BATTLE_STARS_WIN
        assert session.status == "finished"

    def test_forfeit_commits(self):
        db = MagicMock()
        session = _make_session()
        svc = _make_svc(db=db)

        svc.forfeit(session, "user-1")

        db.commit.assert_called_once()

    def test_forfeit_on_non_active_session_is_noop(self):
        db = MagicMock()
        session = _make_session(status="finished", winner_id="user-1")
        svc = _make_svc(db=db)

        svc.forfeit(session, "user-1")

        assert session.winner_id == "user-1"  # unchanged
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# questions_for_client
# ---------------------------------------------------------------------------


class TestQuestionsForClient:
    def _questions(self):
        return [
            {
                "id": 1,
                "subject_id": 10,
                "subject_name": "Математика",
                "text": "Найдите производную f(x)=3x²",
                "variants": [
                    {"id": 100, "text": "6x"},
                    {"id": 101, "text": "3x"},
                ],
                "correct_variant_id": 100,
                "explanation": "По правилу (xⁿ)′ = nxⁿ⁻¹.",
            }
        ]

    def test_correct_variant_id_not_exposed_to_client(self):
        result = questions_for_client(self._questions())
        assert not hasattr(result[0], "correct_variant_id")

    def test_explanation_included(self):
        result = questions_for_client(self._questions())
        assert result[0].explanation == "По правилу (xⁿ)′ = nxⁿ⁻¹."

    def test_explanation_none_when_key_absent(self):
        q = {
            "id": 2,
            "subject_id": 11,
            "subject_name": "Физика",
            "text": "Скорость света?",
            "variants": [{"id": 200, "text": "3×10⁸ м/с"}],
            "correct_variant_id": 200,
        }
        result = questions_for_client([q])
        assert result[0].explanation is None

    def test_variants_count_preserved(self):
        result = questions_for_client(self._questions())
        assert len(result[0].variants) == 2
        assert result[0].variants[0].id == 100

    def test_subject_name_preserved(self):
        result = questions_for_client(self._questions())
        assert result[0].subject_name == "Математика"


# ---------------------------------------------------------------------------
# build_correct_answers
# ---------------------------------------------------------------------------


class TestBuildCorrectAnswers:
    def test_maps_question_id_to_correct_variant_id(self):
        questions = [
            {"id": 1, "correct_variant_id": 100},
            {"id": 2, "correct_variant_id": 200},
        ]
        result = build_correct_answers(questions)
        assert result == {"1": 100, "2": 200}

    def test_skips_none_correct_variant(self):
        questions = [
            {"id": 1, "correct_variant_id": 100},
            {"id": 2, "correct_variant_id": None},
        ]
        result = build_correct_answers(questions)
        assert "2" not in result
        assert result == {"1": 100}

    def test_skips_question_without_correct_variant_key(self):
        questions = [
            {"id": 1, "correct_variant_id": 100},
            {"id": 2},  # key absent
        ]
        result = build_correct_answers(questions)
        assert "2" not in result

    def test_empty_input_returns_empty_dict(self):
        assert build_correct_answers([]) == {}
