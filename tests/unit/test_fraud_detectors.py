"""Unit tests for anti-fraud detectors in EntAttemptService.

Tests _detect_bot_speed and _detect_answer_patterns with mocked UoW
and session — no DB required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from quiz.services.ent_attempts import EntAttemptService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> tuple[EntAttemptService, MagicMock]:
    uow = MagicMock()
    uow.fraud_events = MagicMock()
    uow.fraud_events.log_event = MagicMock()
    session = MagicMock()
    uow.session = session
    cache = MagicMock()
    cashback = MagicMock()
    svc = EntAttemptService(uow=uow, cache_service=cache, cashback_service=cashback)
    return svc, uow


def _attempt_stat(spend_time: int, total_questions: int):
    return SimpleNamespace(spend_time=spend_time, total_questions=total_questions, score=80)


def _ent_attempt(exam_type_value: str = "full_exam"):
    attempt = MagicMock()
    attempt.id = 42
    attempt.exam_type = SimpleNamespace(value=exam_type_value)
    return attempt


def _answer_dto(questions: list[dict]):
    """Build a mock answer DTO from list of {question_id, variants}."""
    qs = []
    for q in questions:
        item = SimpleNamespace(
            question_id=q["question_id"],
            variants=q["variants"],
        )
        qs.append(item)
    return SimpleNamespace(questions=qs)


# ---------------------------------------------------------------------------
# _detect_bot_speed
# ---------------------------------------------------------------------------

class TestDetectBotSpeed:
    def test_fires_when_avg_below_threshold(self):
        svc, uow = _make_service()
        uid = uuid4()
        # 120 questions in 100 seconds → 0.83 sec/q < 2 threshold
        stat = _attempt_stat(spend_time=100, total_questions=120)
        svc._detect_bot_speed(stat, _ent_attempt(), uid)
        uow.fraud_events.log_event.assert_called_once()
        kwargs = uow.fraud_events.log_event.call_args[1]
        assert kwargs["event_type"] == "bot_speed_answers"
        assert kwargs["risk_score"] == 90
        assert kwargs["user_id"] == uid

    def test_no_fire_when_speed_normal(self):
        svc, uow = _make_service()
        # 120 questions in 600 seconds → 5 sec/q > 2 threshold
        stat = _attempt_stat(spend_time=600, total_questions=120)
        svc._detect_bot_speed(stat, _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_no_fire_below_min_questions(self):
        svc, uow = _make_service()
        # Only 5 questions — below MIN_QUESTIONS_FOR_DETECTION
        stat = _attempt_stat(spend_time=5, total_questions=5)
        svc._detect_bot_speed(stat, _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_boundary_exactly_at_threshold(self):
        svc, uow = _make_service()
        # 2 sec/q exactly — NOT below threshold (strict <)
        stat = _attempt_stat(spend_time=240, total_questions=120)
        svc._detect_bot_speed(stat, _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_metadata_contains_avg_speed(self):
        svc, uow = _make_service()
        stat = _attempt_stat(spend_time=100, total_questions=120)
        svc._detect_bot_speed(stat, _ent_attempt(), uuid4())
        meta = uow.fraud_events.log_event.call_args[1]["metadata"]
        assert meta["avg_seconds_per_question"] == round(100 / 120, 2)


# ---------------------------------------------------------------------------
# _detect_answer_patterns
# ---------------------------------------------------------------------------

class TestDetectAnswerPatterns:
    def _mock_variant_query(self, uow: MagicMock, variant_rows: list[tuple]):
        """Set up uow.session.query(...).filter(...).order_by(...).all() to return rows."""
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = variant_rows
        uow.session.query.return_value = query_mock

    def test_fires_on_dominant_position(self):
        svc, uow = _make_service()
        uid = uuid4()

        # 15 questions, each has variants [10, 20, 30] (ids in order)
        # User always picks variant_id=10 (position 0)
        variant_rows = [(10 + i * 3, (i + 1)) for i in range(15)] + \
                       [(11 + i * 3, (i + 1)) for i in range(15)] + \
                       [(12 + i * 3, (i + 1)) for i in range(15)]
        # Simplify: q1 has variants [1,2,3], q2 has [4,5,6], etc.
        # User always picks variant at index 0
        questions = []
        variant_rows_clean = []
        for i in range(15):
            q_id = i + 1
            v_ids = [q_id * 10, q_id * 10 + 1, q_id * 10 + 2]  # 3 variants per question
            variant_rows_clean += [(v, q_id) for v in v_ids]
            questions.append({"question_id": q_id, "variants": [q_id * 10]})  # picks first

        self._mock_variant_query(uow, variant_rows_clean)
        answer = _answer_dto(questions)
        svc._detect_answer_patterns(answer, _ent_attempt(), uid)

        uow.fraud_events.log_event.assert_called_once()
        kwargs = uow.fraud_events.log_event.call_args[1]
        assert kwargs["event_type"] == "pattern_answers"
        assert kwargs["risk_score"] == 60
        assert kwargs["metadata"]["dominant_position"] == 0
        assert kwargs["metadata"]["frequency_percent"] == 100.0

    def test_no_fire_on_varied_answers(self):
        svc, uow = _make_service()
        # 15 questions, user picks different positions
        questions = []
        variant_rows = []
        for i in range(15):
            q_id = i + 1
            v_ids = [q_id * 10, q_id * 10 + 1, q_id * 10 + 2, q_id * 10 + 3]
            variant_rows += [(v, q_id) for v in v_ids]
            # Rotate through positions 0,1,2,3
            selected = v_ids[i % 4]
            questions.append({"question_id": q_id, "variants": [selected]})

        self._mock_variant_query(uow, variant_rows)
        svc._detect_answer_patterns(_answer_dto(questions), _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_no_fire_below_min_questions(self):
        svc, uow = _make_service()
        # Only 5 questions answered
        questions = [{"question_id": i, "variants": [i * 10]} for i in range(1, 6)]
        variant_rows = [(i * 10, i) for i in range(1, 6)]
        self._mock_variant_query(uow, variant_rows)
        svc._detect_answer_patterns(_answer_dto(questions), _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_no_fire_when_no_questions(self):
        svc, uow = _make_service()
        svc._detect_answer_patterns(_answer_dto([]), _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_79_percent_does_not_fire(self):
        svc, uow = _make_service()
        # 15 questions, 11 with position 0 (73%), 4 with position 1
        questions = []
        variant_rows = []
        for i in range(15):
            q_id = i + 1
            v_ids = [q_id * 10, q_id * 10 + 1, q_id * 10 + 2]
            variant_rows += [(v, q_id) for v in v_ids]
            selected = v_ids[0] if i < 11 else v_ids[1]  # 11/15 = 73%
            questions.append({"question_id": q_id, "variants": [selected]})

        self._mock_variant_query(uow, variant_rows)
        svc._detect_answer_patterns(_answer_dto(questions), _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_not_called()

    def test_80_percent_fires(self):
        svc, uow = _make_service()
        # 15 questions, 12 with position 0 (80%)
        questions = []
        variant_rows = []
        for i in range(15):
            q_id = i + 1
            v_ids = [q_id * 10, q_id * 10 + 1, q_id * 10 + 2]
            variant_rows += [(v, q_id) for v in v_ids]
            selected = v_ids[0] if i < 12 else v_ids[1]  # 12/15 = 80%
            questions.append({"question_id": q_id, "variants": [selected]})

        self._mock_variant_query(uow, variant_rows)
        svc._detect_answer_patterns(_answer_dto(questions), _ent_attempt(), uuid4())
        uow.fraud_events.log_event.assert_called_once()
