"""Unit tests for anti-fraud detectors in EntAttemptService and LoginEventLogger.

Tests _detect_bot_speed, _detect_answer_patterns, _detect_rapid_attempts,
_detect_score_spike, _detect_missing_device_id, _detect_multi_account,
_detect_multi_account_ip, log_referral_redeem/_detect_referral_device_farm,
and promo_bypass in PromocodeService.

All external dependencies are mocked — no DB, no Redis, no network.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from quiz.services.ent_attempts import EntAttemptService
from security.login_event_logger import LoginEventLogger


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


# ===========================================================================
# Helpers for new detectors
# ===========================================================================

def _make_ent_service_with_redis(redis_mock=None, app_settings_mock=None):
    uow = MagicMock()
    cache = MagicMock()
    if redis_mock is not None:
        cache.redis = redis_mock
    else:
        cache.redis = MagicMock()
    return EntAttemptService(uow=uow, cache_service=cache, cashback_service=MagicMock(),
                             app_settings=app_settings_mock)


def _make_redis(incr_return=1, exists_return=False):
    r = MagicMock()
    r.incr.return_value = incr_return
    r.exists.return_value = 1 if exists_return else 0
    r.expire.return_value = True
    r.setex.return_value = True
    return r


def _make_login_logger(redis_mock=None):
    db = MagicMock()
    db.session = MagicMock()
    return LoginEventLogger(database=db, redis=redis_mock or MagicMock())


def _mock_session_count(session, count):
    q = MagicMock()
    session.query.return_value = q
    q.filter.return_value = q
    q.scalar.return_value = count


# ===========================================================================
# EntAttemptService._detect_rapid_attempts
# ===========================================================================

class TestRapidAttemptsDetector:
    """Redis INCR counter; fires 'rapid_attempts' (risk=70) at count EXACTLY 10."""

    def test_first_attempt_no_alert(self):
        redis = _make_redis(incr_return=1)
        svc = _make_ent_service_with_redis(redis)
        svc._detect_rapid_attempts(uuid4())
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_first_incr_sets_expiry_on_counter(self):
        redis = _make_redis(incr_return=1)
        svc = _make_ent_service_with_redis(redis)
        user_id = uuid4()
        svc._detect_rapid_attempts(user_id)
        redis.expire.assert_called_once()
        key_arg = redis.expire.call_args[0][0]
        assert str(user_id) in key_arg

    def test_nine_attempts_no_alert(self):
        redis = _make_redis(incr_return=9)
        svc = _make_ent_service_with_redis(redis)
        svc._detect_rapid_attempts(uuid4())
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_tenth_attempt_fires_alert(self):
        redis = _make_redis(incr_return=10, exists_return=False)
        svc = _make_ent_service_with_redis(redis)
        user_id = uuid4()
        svc._detect_rapid_attempts(user_id)
        svc._uow.fraud_events.log_event.assert_called_once()
        kw = svc._uow.fraud_events.log_event.call_args[1]
        assert kw["event_type"] == "rapid_attempts"
        assert kw["risk_score"] == 70
        assert kw["user_id"] == user_id

    def test_tenth_attempt_sets_dedup_key(self):
        redis = _make_redis(incr_return=10, exists_return=False)
        svc = _make_ent_service_with_redis(redis)
        user_id = uuid4()
        svc._detect_rapid_attempts(user_id)
        redis.setex.assert_called_once()
        dedup_key = redis.setex.call_args[0][0]
        assert str(user_id) in dedup_key

    def test_tenth_attempt_dedup_prevents_alert(self):
        redis = _make_redis(incr_return=10, exists_return=True)
        svc = _make_ent_service_with_redis(redis)
        svc._detect_rapid_attempts(uuid4())
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_eleventh_attempt_no_alert(self):
        # Fires EXACTLY at count==10, not >=10
        redis = _make_redis(incr_return=11, exists_return=False)
        svc = _make_ent_service_with_redis(redis)
        svc._detect_rapid_attempts(uuid4())
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_missing_redis_attribute_returns_silently(self):
        svc = _make_ent_service_with_redis()
        del svc._cache_service.redis
        svc._detect_rapid_attempts(uuid4())  # must not raise

    def test_metadata_contains_count_and_threshold(self):
        redis = _make_redis(incr_return=10, exists_return=False)
        svc = _make_ent_service_with_redis(redis)
        svc._detect_rapid_attempts(uuid4())
        meta = svc._uow.fraud_events.log_event.call_args[1]["metadata"]
        assert meta["attempts_in_window"] == 10
        assert meta["threshold"] == 10


# ===========================================================================
# EntAttemptService._detect_score_spike
# ===========================================================================

class TestScoreSpikeDetector:
    """PointsAuditLog SUM over 24h; fires when >= daily_limit (default 10 000)."""

    def _svc(self, daily_total, limit=10_000, dedup_exists=False):
        app_settings = MagicMock()
        app_settings.get_int.return_value = limit
        redis = _make_redis(exists_return=dedup_exists)
        svc = _make_ent_service_with_redis(redis, app_settings)
        _mock_session_count(svc._uow.session, daily_total)
        return svc

    def test_zero_points_awarded_returns_early(self):
        svc = self._svc(99_999)
        svc._detect_score_spike(uuid4(), points_just_awarded=0)
        svc._uow.fraud_events.log_event.assert_not_called()
        # session should not be queried
        svc._uow.session.query.assert_not_called()

    def test_under_limit_no_alert(self):
        svc = self._svc(9_999)
        svc._detect_score_spike(uuid4(), points_just_awarded=1)
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_at_limit_fires_alert(self):
        svc = self._svc(10_000)
        user_id = uuid4()
        svc._detect_score_spike(user_id, points_just_awarded=100)
        svc._uow.fraud_events.log_event.assert_called_once()
        kw = svc._uow.fraud_events.log_event.call_args[1]
        assert kw["event_type"] == "score_spike"
        assert kw["risk_score"] == 75
        assert kw["user_id"] == user_id

    def test_over_limit_fires_alert(self):
        svc = self._svc(25_000)
        svc._detect_score_spike(uuid4(), points_just_awarded=500)
        svc._uow.fraud_events.log_event.assert_called_once()

    def test_dedup_prevents_alert(self):
        svc = self._svc(20_000, dedup_exists=True)
        svc._detect_score_spike(uuid4(), points_just_awarded=1)
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_custom_limit_from_app_settings_lower(self):
        svc = self._svc(3_001, limit=3_000)
        svc._detect_score_spike(uuid4(), points_just_awarded=1)
        svc._uow.fraud_events.log_event.assert_called_once()

    def test_custom_limit_from_app_settings_higher_no_alert(self):
        svc = self._svc(10_000, limit=50_000)
        svc._detect_score_spike(uuid4(), points_just_awarded=100)
        svc._uow.fraud_events.log_event.assert_not_called()

    def test_no_app_settings_uses_default_10k(self):
        redis = _make_redis(exists_return=False)
        svc = _make_ent_service_with_redis(redis, app_settings_mock=None)
        _mock_session_count(svc._uow.session, 10_001)
        svc._detect_score_spike(uuid4(), points_just_awarded=1)
        svc._uow.fraud_events.log_event.assert_called_once()

    def test_metadata_contains_expected_fields(self):
        svc = self._svc(12_000, limit=10_000)
        svc._detect_score_spike(uuid4(), points_just_awarded=200)
        meta = svc._uow.fraud_events.log_event.call_args[1]["metadata"]
        assert meta["daily_total"] == 12_000
        assert meta["daily_limit"] == 10_000
        assert meta["just_awarded"] == 200


# ===========================================================================
# LoginEventLogger._detect_missing_device_id
# ===========================================================================

class TestMissingDeviceIdDetector:
    """Fires 'missing_device_id' (risk=45) once per user per 24h when device absent."""

    def test_fires_event_with_redis(self):
        redis = _make_redis(exists_return=False)
        logger = _make_login_logger(redis)
        repo = MagicMock()
        user_id = uuid4()
        logger._detect_missing_device_id(repo, user_id)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "missing_device_id"
        assert kw["risk_score"] == 45
        assert kw["user_id"] == user_id

    def test_fires_event_without_redis(self):
        # redis=None → skips dedup but still logs event
        logger = LoginEventLogger(database=MagicMock(), redis=None)
        repo = MagicMock()
        logger._detect_missing_device_id(repo, uuid4())
        repo.log_event.assert_called_once()

    def test_dedup_key_ttl_is_24h(self):
        redis = _make_redis(exists_return=False)
        logger = _make_login_logger(redis)
        user_id = uuid4()
        logger._detect_missing_device_id(MagicMock(), user_id)
        redis.setex.assert_called_once()
        _, ttl, _ = redis.setex.call_args[0]
        assert ttl == 24 * 3600

    def test_dedup_key_contains_user_id(self):
        redis = _make_redis(exists_return=False)
        logger = _make_login_logger(redis)
        user_id = uuid4()
        logger._detect_missing_device_id(MagicMock(), user_id)
        key = redis.setex.call_args[0][0]
        assert str(user_id) in key

    def test_dedup_prevents_second_alert(self):
        redis = _make_redis(exists_return=True)
        logger = _make_login_logger(redis)
        repo = MagicMock()
        logger._detect_missing_device_id(repo, uuid4())
        repo.log_event.assert_not_called()

    def test_redis_exception_swallowed(self):
        redis = MagicMock()
        redis.exists.side_effect = Exception("Redis down")
        logger = _make_login_logger(redis)
        logger._detect_missing_device_id(MagicMock(), uuid4())  # must not raise


# ===========================================================================
# LoginEventLogger._detect_multi_account (device_id)
# ===========================================================================

class TestMultiAccountDeviceDetector:
    """Fires 'multi_account_device' (risk=70) when ≥3 user_ids share a device in 30d."""

    def _call(self, distinct_users, dedup_exists=False):
        redis = _make_redis(exists_return=dedup_exists)
        logger = _make_login_logger(redis)
        session = MagicMock()
        _mock_session_count(session, distinct_users)
        repo = MagicMock()
        user_id = uuid4()
        logger._detect_multi_account(repo, session, user_id, "dev-abc-123")
        return repo, user_id

    def test_two_users_no_alert(self):
        repo, _ = self._call(2)
        repo.log_event.assert_not_called()

    def test_three_users_fires_alert(self):
        repo, user_id = self._call(3)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "multi_account_device"
        assert kw["risk_score"] == 70
        assert kw["user_id"] == user_id
        assert kw["device_id"] == "dev-abc-123"

    def test_five_users_fires_alert(self):
        repo, _ = self._call(5)
        repo.log_event.assert_called_once()

    def test_dedup_prevents_alert(self):
        repo, _ = self._call(3, dedup_exists=True)
        repo.log_event.assert_not_called()

    def test_metadata_has_distinct_count_and_threshold(self):
        repo, _ = self._call(4)
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["distinct_users"] == 4
        assert meta["device_id"] == "dev-abc-123"
        assert meta["threshold"] == 3

    def test_db_exception_swallowed(self):
        redis = _make_redis()
        logger = _make_login_logger(redis)
        bad_session = MagicMock()
        bad_session.query.side_effect = Exception("DB error")
        logger._detect_multi_account(MagicMock(), bad_session, uuid4(), "dev-x")  # must not raise


# ===========================================================================
# LoginEventLogger._detect_multi_account_ip
# ===========================================================================

class TestMultiAccountIpDetector:
    """Fires 'multi_account_ip' (risk=60) when ≥5 user_ids share an IP in 24h."""

    def _call(self, distinct_users, dedup_exists=False):
        redis = _make_redis(exists_return=dedup_exists)
        logger = _make_login_logger(redis)
        session = MagicMock()
        _mock_session_count(session, distinct_users)
        repo = MagicMock()
        user_id = uuid4()
        logger._detect_multi_account_ip(repo, session, user_id, "1.2.3.4")
        return repo, user_id

    def test_four_users_no_alert(self):
        repo, _ = self._call(4)
        repo.log_event.assert_not_called()

    def test_five_users_fires_alert(self):
        repo, user_id = self._call(5)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "multi_account_ip"
        assert kw["risk_score"] == 60
        assert kw["user_id"] == user_id
        assert kw["ip_address"] == "1.2.3.4"

    def test_ten_users_fires_alert(self):
        repo, _ = self._call(10)
        repo.log_event.assert_called_once()

    def test_dedup_prevents_alert(self):
        repo, _ = self._call(5, dedup_exists=True)
        repo.log_event.assert_not_called()

    def test_metadata_has_ip_and_threshold(self):
        repo, _ = self._call(6)
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["ip"] == "1.2.3.4"
        assert meta["threshold"] == 5
        assert meta["distinct_users"] == 6

    def test_db_exception_swallowed(self):
        redis = _make_redis()
        logger = _make_login_logger(redis)
        bad = MagicMock()
        bad.query.side_effect = Exception("DB error")
        logger._detect_multi_account_ip(MagicMock(), bad, uuid4(), "9.9.9.9")  # must not raise


# ===========================================================================
# LoginEventLogger.log_referral_redeem / _detect_referral_device_farm
# ===========================================================================

class TestReferralDeviceFarmDetector:
    """Fires 'referral_device_farm' (risk=75) when ≥3 accounts from same device redeemed."""

    def _run(self, distinct_users, dedup_exists=False, device_id="dev-farm-001"):
        redis = _make_redis(exists_return=dedup_exists)
        logger = _make_login_logger(redis)
        session = MagicMock()
        _mock_session_count(session, distinct_users)
        logger._database.session = session
        invitee_id = uuid4()
        inviter_id = uuid4()
        with patch("security.login_event_logger.FraudEventRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            logger.log_referral_redeem(
                invitee_id=invitee_id,
                inviter_id=inviter_id,
                device_id=device_id,
            )
        return mock_repo, inviter_id, invitee_id

    def test_no_device_id_returns_immediately(self):
        logger = _make_login_logger()
        with patch("security.login_event_logger.FraudEventRepository") as MockRepo:
            logger.log_referral_redeem(invitee_id=uuid4(), inviter_id=uuid4(), device_id=None)
        MockRepo.assert_not_called()

    def test_two_users_no_alert(self):
        repo, _, _ = self._run(2)
        repo.log_event.assert_not_called()

    def test_three_users_fires_alert(self):
        repo, inviter_id, _ = self._run(3)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "referral_device_farm"
        assert kw["risk_score"] == 75
        assert kw["user_id"] == inviter_id
        assert kw["device_id"] == "dev-farm-001"

    def test_metadata_includes_invitee_inviter_and_count(self):
        repo, inviter_id, invitee_id = self._run(4)
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["inviter_id"] == str(inviter_id)
        assert meta["invitee_id"] == str(invitee_id)
        assert meta["distinct_users"] == 4
        assert meta["threshold"] == 3

    def test_dedup_prevents_repeat_alert(self):
        repo, _, _ = self._run(5, dedup_exists=True)
        repo.log_event.assert_not_called()

    def test_exception_in_db_is_swallowed(self):
        redis = _make_redis()
        logger = _make_login_logger(redis)
        logger._database.session = MagicMock(side_effect=Exception("DB down"))
        # Must not raise
        logger.log_referral_redeem(invitee_id=uuid4(), inviter_id=uuid4(), device_id="dev-x")


# ===========================================================================
# PromocodeService — promo_bypass fraud event
# ===========================================================================

class TestPromoBypas:
    """promo_bypass FraudEvent is logged on repeat activation of a non-reusable code."""

    def _make_service(self):
        from promocodes.service import PromocodeService
        db = MagicMock()
        svc = PromocodeService(db_session=db, subscription_service=MagicMock())
        return svc, db

    def _setup_db(self, db, promo, existing_usage):
        """Wire db.execute (rowcount=1) and db.query().filter().first() chain."""
        exec_result = MagicMock()
        exec_result.rowcount = 1
        db.execute.return_value = exec_result
        # query().filter().first() side_effect: first call → promo, second → existing_usage
        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value = q
        q.first.side_effect = [promo, existing_usage]

    def _make_promo(self, is_reusable=False):
        from promocodes.models import Promocode
        p = MagicMock(spec=Promocode)
        p.id = 42
        p.code = "TESTCODE"
        p.is_reusable = is_reusable
        p.duration_days = 30
        p.plan_type = "PRO"
        p.is_trial = False
        p.expires_at = None
        return p

    @pytest.mark.asyncio
    async def test_second_activation_logs_promo_bypass_and_raises_400(self):
        from fastapi import HTTPException
        from promocodes.models import PromocodeUsage

        svc, db = self._make_service()
        promo = self._make_promo(is_reusable=False)
        existing = MagicMock(spec=PromocodeUsage)
        existing.created_at = None
        self._setup_db(db, promo, existing)

        user = MagicMock()
        user.id = uuid4()

        # FraudEventRepository is lazily imported inside the function body,
        # so patch it at the source module, not at promocodes.service.
        with patch("security.repository.FraudEventRepository") as MockFraud:
            mock_repo = MockFraud.return_value
            with pytest.raises(HTTPException) as exc:
                await svc.activate_promocode(user, "TESTCODE")

        assert exc.value.status_code == 400
        mock_repo.log_event.assert_called_once()
        kw = mock_repo.log_event.call_args[1]
        assert kw["event_type"] == "promo_bypass"
        assert kw["risk_score"] == 65
        assert kw["user_id"] == user.id

    @pytest.mark.asyncio
    async def test_second_activation_metadata_contains_code_and_promo_id(self):
        from fastapi import HTTPException
        from promocodes.models import PromocodeUsage

        svc, db = self._make_service()
        promo = self._make_promo(is_reusable=False)
        existing = MagicMock(spec=PromocodeUsage)
        existing.created_at = None
        self._setup_db(db, promo, existing)

        user = MagicMock()
        user.id = uuid4()

        with patch("security.repository.FraudEventRepository") as MockFraud:
            mock_repo = MockFraud.return_value
            with pytest.raises(HTTPException):
                await svc.activate_promocode(user, "TESTCODE")

        meta = mock_repo.log_event.call_args[1]["metadata"]
        assert meta["promocode_id"] == 42
        assert meta["code"] == "TESTCODE"

    @pytest.mark.asyncio
    async def test_first_activation_no_fraud_event(self):
        svc, db = self._make_service()
        promo = self._make_promo(is_reusable=False)
        self._setup_db(db, promo, None)  # None = no prior usage

        user = MagicMock()
        user.id = uuid4()

        # After bypass check, service proceeds to create PromocodeUsage and call subscription_service.
        # We let subscription_service raise to abort early without completing the full flow.
        svc.subscription_service.activate_subscription = MagicMock(side_effect=Exception("stop"))

        with patch("security.repository.FraudEventRepository") as MockFraud:
            try:
                await svc.activate_promocode(user, "TESTCODE")
            except Exception:
                pass

        MockFraud.return_value.log_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_reusable_promo_no_bypass_check(self):
        """Reusable codes skip the one-per-user check entirely — no fraud event regardless."""
        svc, db = self._make_service()
        promo = self._make_promo(is_reusable=True)
        self._setup_db(db, promo, None)

        user = MagicMock()
        user.id = uuid4()
        svc.subscription_service.activate_subscription = MagicMock(side_effect=Exception("stop"))

        with patch("security.repository.FraudEventRepository") as MockFraud:
            try:
                await svc.activate_promocode(user, "TESTCODE")
            except Exception:
                pass

        MockFraud.return_value.log_event.assert_not_called()


# ===========================================================================
# LoginEventLogger._detect_brute_force
# ===========================================================================

class TestBruteForceDetector:
    """Fires 'brute_force' (risk=90) when ip_count OR login_count >= 20 in 10 min."""

    _THRESHOLD = 20

    def _call(self, ip_count, login_count=0, dedup_exists=False, login_identifier="+77001234567"):
        redis = MagicMock()
        # incr() called: first for IP key, then (if login_identifier) for login key
        redis.incr.side_effect = [ip_count, login_count] if login_identifier else [ip_count]
        redis.exists.return_value = 1 if dedup_exists else 0
        redis.expire.return_value = True
        redis.setex.return_value = True
        logger = _make_login_logger(redis)
        repo = MagicMock()
        logger._detect_brute_force(repo, "1.2.3.4", login_identifier)
        return repo, redis

    def test_below_threshold_no_alert(self):
        repo, _ = self._call(ip_count=19, login_count=0, login_identifier=None)
        repo.log_event.assert_not_called()

    def test_ip_count_at_threshold_fires(self):
        repo, _ = self._call(ip_count=20, login_count=1)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "brute_force"
        assert kw["risk_score"] == 90
        assert kw["ip_address"] == "1.2.3.4"

    def test_ip_count_above_threshold_fires(self):
        repo, _ = self._call(ip_count=35, login_count=1)
        repo.log_event.assert_called_once()

    def test_login_count_at_threshold_fires_even_if_ip_low(self):
        repo, _ = self._call(ip_count=1, login_count=20)
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "brute_force"

    def test_both_counts_below_no_alert(self):
        repo, _ = self._call(ip_count=19, login_count=19)
        repo.log_event.assert_not_called()

    def test_dedup_prevents_second_alert(self):
        repo, _ = self._call(ip_count=20, login_count=1, dedup_exists=True)
        repo.log_event.assert_not_called()

    def test_first_ip_incr_sets_ttl(self):
        _, redis = self._call(ip_count=1, login_count=1)
        # expire called at least once (ip key and login key both hit count==1)
        assert redis.expire.call_count >= 1
        keys_expired = [c[0][0] for c in redis.expire.call_args_list]
        assert any("1.2.3.4" in k for k in keys_expired)

    def test_no_login_identifier_skips_login_key(self):
        _, redis = self._call(ip_count=5, login_count=0, login_identifier=None)
        # incr called only once (ip key only)
        assert redis.incr.call_count == 1

    def test_metadata_contains_both_counts_and_identifier(self):
        repo, _ = self._call(ip_count=20, login_count=5)
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["ip_count"] == 20
        assert meta["login_count"] == 5
        assert meta["login_identifier"] == "+77001234567"

    def test_exception_in_redis_swallowed(self):
        redis = MagicMock()
        redis.incr.side_effect = Exception("Redis down")
        logger = _make_login_logger(redis)
        logger._detect_brute_force(MagicMock(), "1.2.3.4", "+77001234567")  # must not raise


# ===========================================================================
# LoginEventLogger._detect_suspicious_city
# ===========================================================================

class TestSuspiciousCityDetector:
    """Fires 'suspicious_login' (risk=65) when user's city changed since last login."""

    def _call(self, last_city_raw, current_city, ip="1.2.3.4"):
        """
        last_city_raw: bytes (e.g. b"Almaty") or None (first login).
        current_city:  str city name or None.
        """
        redis = MagicMock()
        redis.get.return_value = last_city_raw
        logger = _make_login_logger(redis)
        repo = MagicMock()
        user_id = uuid4()
        logger._detect_suspicious_city(repo, user_id, ip, current_city)
        return repo, redis, user_id

    def test_city_none_returns_early(self):
        repo, redis, _ = self._call(b"Almaty", None)
        repo.log_event.assert_not_called()
        redis.get.assert_not_called()  # returns before touching Redis

    def test_first_login_no_last_city_no_alert(self):
        repo, redis, _ = self._call(None, "Almaty")
        repo.log_event.assert_not_called()

    def test_first_login_stores_city(self):
        _, redis, user_id = self._call(None, "Almaty")
        redis.setex.assert_called_once()
        key, _, value = redis.setex.call_args[0]
        assert str(user_id) in key
        assert value == "Almaty"

    def test_same_city_no_alert(self):
        repo, _, _ = self._call(b"Almaty", "Almaty")
        repo.log_event.assert_not_called()

    def test_city_changed_fires_alert(self):
        repo, _, user_id = self._call(b"Almaty", "Astana", ip="5.6.7.8")
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "suspicious_login"
        assert kw["risk_score"] == 65
        assert kw["user_id"] == user_id
        assert kw["ip_address"] == "5.6.7.8"

    def test_city_changed_metadata(self):
        repo, _, _ = self._call(b"Almaty", "Astana", ip="5.6.7.8")
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["prev_city"] == "Almaty"
        assert meta["new_city"] == "Astana"
        assert meta["ip"] == "5.6.7.8"

    def test_city_always_updated_in_redis_on_change(self):
        _, redis, _ = self._call(b"Almaty", "Astana")
        redis.setex.assert_called_once()
        _, _, stored = redis.setex.call_args[0]
        assert stored == "Astana"

    def test_city_always_updated_even_when_same(self):
        _, redis, _ = self._call(b"Almaty", "Almaty")
        redis.setex.assert_called_once()

    def test_exception_in_redis_swallowed(self):
        redis = MagicMock()
        redis.get.side_effect = Exception("Redis down")
        logger = _make_login_logger(redis)
        logger._detect_suspicious_city(MagicMock(), uuid4(), "1.2.3.4", "Almaty")  # must not raise


# ===========================================================================
# _suspicious_subscription_checker (lifespan background task)
# ===========================================================================

class TestSuspiciousSubscriptionChecker:
    """Hourly task: flag PRO subs with no payment and no promo code."""

    async def _run_one_cycle(self, suspects):
        """Run the checker for exactly one cycle, return the mock FraudEventRepository."""
        import asyncio as _asyncio
        from api.lifespan import _suspicious_subscription_checker

        mock_session = MagicMock()
        q = MagicMock()
        mock_session.query.return_value = q
        q.filter.return_value = q
        q.limit.return_value = q
        q.all.return_value = suspects

        mock_db = MagicMock()
        mock_db.session = mock_session

        mock_repo = MagicMock()

        sleep_call = 0

        async def one_shot(n):
            nonlocal sleep_call
            sleep_call += 1
            if sleep_call >= 2:
                raise _asyncio.CancelledError()

        with patch("database.database.Database", return_value=mock_db), \
             patch("security.repository.FraudEventRepository", return_value=mock_repo), \
             patch("api.lifespan.asyncio.sleep", side_effect=one_shot):
            try:
                await _suspicious_subscription_checker(MagicMock())
            except _asyncio.CancelledError:
                pass

        return mock_repo, mock_session

    @pytest.mark.asyncio
    async def test_no_suspects_no_log_event(self):
        repo, _ = await self._run_one_cycle(suspects=[])
        repo.log_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_suspect_logs_pro_without_payment(self):
        uid = uuid4()
        repo, _ = await self._run_one_cycle(suspects=[(uid,)])
        repo.log_event.assert_called_once()
        kw = repo.log_event.call_args[1]
        assert kw["event_type"] == "pro_without_payment"
        assert kw["risk_score"] == 80
        assert str(kw["user_id"]) == str(uid)

    @pytest.mark.asyncio
    async def test_multiple_suspects_all_logged(self):
        uids = [uuid4(), uuid4(), uuid4()]
        repo, _ = await self._run_one_cycle(suspects=[(u,) for u in uids])
        assert repo.log_event.call_count == 3

    @pytest.mark.asyncio
    async def test_session_committed_after_logging(self):
        uid = uuid4()
        _, session = await self._run_one_cycle(suspects=[(uid,)])
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_closed_in_finally(self):
        # Even with empty suspects, session must be closed
        _, session = await self._run_one_cycle(suspects=[])
        session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_metadata_contains_user_id(self):
        uid = uuid4()
        repo, _ = await self._run_one_cycle(suspects=[(uid,)])
        meta = repo.log_event.call_args[1]["metadata"]
        assert meta["user_id"] == str(uid)


# ===========================================================================
# LoginEventLogger._write_event — detector dispatch integration
# ===========================================================================

class TestWriteEventDetectorDispatch:
    """Verify that _write_event calls the right detectors under the right conditions."""

    def _write(self, success=True, user_id=None, ip="1.2.3.4",
               device_id=None, city=None):
        uid = user_id or uuid4()
        logger = _make_login_logger(redis_mock=MagicMock())
        with patch.object(logger, "_detect_brute_force") as mock_bf, \
             patch.object(logger, "_detect_suspicious_city") as mock_sc, \
             patch.object(logger, "_detect_multi_account") as mock_ma, \
             patch.object(logger, "_detect_missing_device_id") as mock_md, \
             patch.object(logger, "_detect_multi_account_ip") as mock_ip, \
             patch("security.login_event_logger.FraudEventRepository"):
            logger._write_event(
                user_id=uid, ip=ip, city=city, user_agent=None,
                success=success, device_id=device_id,
            )
            return {
                "bf": mock_bf, "sc": mock_sc, "ma": mock_ma,
                "md": mock_md, "ip": mock_ip,
            }, uid

    def test_successful_login_with_device_id_calls_multi_account_and_city(self):
        mocks, _ = self._write(success=True, device_id="dev-1", city="Almaty")
        mocks["ma"].assert_called_once()
        mocks["sc"].assert_called_once()
        mocks["md"].assert_not_called()   # has device_id → skip missing_device_id
        mocks["bf"].assert_not_called()   # success → skip brute_force

    def test_successful_login_without_device_id_calls_missing_device_id(self):
        mocks, _ = self._write(success=True, device_id=None)
        mocks["md"].assert_called_once()
        mocks["ma"].assert_not_called()   # no device_id → skip multi_account

    def test_successful_login_calls_multi_ip_when_ip_present(self):
        mocks, _ = self._write(success=True, device_id="dev-1", ip="1.2.3.4")
        mocks["ip"].assert_called_once()

    def test_failed_login_calls_brute_force_skips_city_and_multi(self):
        mocks, _ = self._write(success=False, ip="1.2.3.4")
        mocks["bf"].assert_called_once()
        mocks["sc"].assert_not_called()
        mocks["ma"].assert_not_called()
        mocks["md"].assert_not_called()

    def test_failed_login_no_ip_skips_brute_force(self):
        mocks, _ = self._write(success=False, ip=None)
        mocks["bf"].assert_not_called()

    def test_no_redis_skips_brute_force(self):
        uid = uuid4()
        logger = LoginEventLogger(database=MagicMock(), redis=None)
        with patch.object(logger, "_detect_brute_force") as mock_bf, \
             patch("security.login_event_logger.FraudEventRepository"):
            logger._write_event(
                user_id=uid, ip="1.2.3.4", city=None,
                user_agent=None, success=False,
            )
        mock_bf.assert_not_called()

    def test_no_redis_skips_suspicious_city(self):
        uid = uuid4()
        logger = LoginEventLogger(database=MagicMock(), redis=None)
        with patch.object(logger, "_detect_suspicious_city") as mock_sc, \
             patch("security.login_event_logger.FraudEventRepository"):
            logger._write_event(
                user_id=uid, ip="1.2.3.4", city="Almaty",
                user_agent=None, success=True, device_id="dev-1",
            )
        mock_sc.assert_not_called()


# ===========================================================================
# Edge-cases
# ===========================================================================

class TestEdgeCases:
    """Miscellaneous edge-cases that don't fit a single detector class."""

    # --- score_spike: Redis down → event still written (dedup try/except pass) ---

    def test_score_spike_redis_down_still_logs_event(self):
        """If redis.exists() throws, the except: pass means log_event is still called."""
        redis = MagicMock()
        redis.exists.side_effect = Exception("Redis timeout")
        app_settings = MagicMock()
        app_settings.get_int.return_value = 10_000
        svc = _make_ent_service_with_redis(redis, app_settings)
        _mock_session_count(svc._uow.session, 20_000)
        svc._detect_score_spike(uuid4(), points_just_awarded=100)
        # Despite Redis failure, event must be logged
        svc._uow.fraud_events.log_event.assert_called_once()
        assert svc._uow.fraud_events.log_event.call_args[1]["event_type"] == "score_spike"

    # --- rapid_attempts error doesn't prevent score_spike (called sequentially) ---

    def test_rapid_attempts_failure_does_not_block_score_spike(self):
        """
        In ent_attempts.py both detectors run back-to-back. Verify that if
        rapid_attempts raises internally, score_spike still executes.
        (Each detector wraps its own logic in try/except at the Redis access point.)
        """
        redis = _make_redis(incr_return=10, exists_return=False)
        app_settings = MagicMock()
        app_settings.get_int.return_value = 10_000
        svc = _make_ent_service_with_redis(redis, app_settings)
        _mock_session_count(svc._uow.session, 20_000)

        # Make rapid_attempts' log_event raise to simulate internal error
        call_count = 0
        original_log_event = svc._uow.fraud_events.log_event

        def patched_log(*, event_type, **kw):
            nonlocal call_count
            call_count += 1
            if event_type == "rapid_attempts":
                raise RuntimeError("DB flake")
            return original_log_event(event_type=event_type, **kw)

        svc._uow.fraud_events.log_event = MagicMock(side_effect=patched_log)

        # rapid_attempts does NOT swallow log_event errors (it's outside try/except)
        # so it propagates; score_spike must be called independently by the caller
        # (ent_attempts.py calls both detectors in sequence, each catches at redis level)
        # We test each detector independently here — they are separate try blocks.
        try:
            svc._detect_rapid_attempts(uuid4())
        except RuntimeError:
            pass  # expected

        svc._uow.fraud_events.log_event.reset_mock()
        svc._detect_score_spike(uuid4(), points_just_awarded=100)
        svc._uow.fraud_events.log_event.assert_called_once()
        assert svc._uow.fraud_events.log_event.call_args[1]["event_type"] == "score_spike"

    # --- referral_farm dedup key contains device_id ---

    def test_referral_farm_dedup_key_contains_device_id(self):
        redis = _make_redis(exists_return=False)
        logger = _make_login_logger(redis)
        session = MagicMock()
        _mock_session_count(session, 4)  # above threshold
        logger._database.session = session
        device_id = "unique-device-xyz-99"
        with patch("security.login_event_logger.FraudEventRepository"):
            logger.log_referral_redeem(
                invitee_id=uuid4(), inviter_id=uuid4(), device_id=device_id
            )
        redis.setex.assert_called_once()
        key = redis.setex.call_args[0][0]
        assert device_id in key

    # --- promo_bypass FraudRepo error doesn't prevent 400 response ---

    @pytest.mark.asyncio
    async def test_promo_bypass_fraud_log_error_does_not_block_400(self):
        """The try/except around fraud logging must not suppress the 400 HTTPException."""
        from fastapi import HTTPException
        from promocodes.models import Promocode, PromocodeUsage
        from promocodes.service import PromocodeService

        db = MagicMock()
        svc = PromocodeService(db_session=db, subscription_service=MagicMock())

        exec_result = MagicMock()
        exec_result.rowcount = 1
        db.execute.return_value = exec_result

        promo = MagicMock(spec=Promocode)
        promo.id = 7
        promo.code = "CODE"
        promo.is_reusable = False
        promo.duration_days = 30
        promo.plan_type = "PRO"
        promo.is_trial = False
        promo.expires_at = None

        existing = MagicMock(spec=PromocodeUsage)
        existing.created_at = None

        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value = q
        q.first.side_effect = [promo, existing]

        user = MagicMock()
        user.id = uuid4()

        # Make FraudEventRepository.log_event raise
        with patch("security.repository.FraudEventRepository") as MockFraud:
            MockFraud.return_value.log_event.side_effect = Exception("DB error in fraud log")
            with pytest.raises(HTTPException) as exc:
                await svc.activate_promocode(user, "CODE")

        # 400 must still be raised despite fraud log failure
        assert exc.value.status_code == 400
