"""Unit tests for LoginEventLogger and geo_service helpers.

Tests geo_service.get_client_ip() parsing and LoginEventLogger.log_login()
with mocked Database and FraudEventRepository — no network calls, no DB.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from security.geo_service import get_client_ip
from security.login_event_logger import LoginEventLogger


# ---------------------------------------------------------------------------
# geo_service.get_client_ip
# ---------------------------------------------------------------------------

def test_get_client_ip_from_x_forwarded_for():
    headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
    assert get_client_ip(headers, "10.0.0.2") == "203.0.113.5"


def test_get_client_ip_from_x_real_ip():
    headers = {"x-real-ip": "198.51.100.7"}
    assert get_client_ip(headers, "127.0.0.1") == "198.51.100.7"


def test_get_client_ip_fallback_to_client_host():
    headers = {}
    assert get_client_ip(headers, "203.0.113.9") == "203.0.113.9"


def test_get_client_ip_none_when_no_info():
    assert get_client_ip({}, None) is None


def test_get_client_ip_x_forwarded_strips_whitespace():
    headers = {"x-forwarded-for": "  203.0.113.1  , 10.0.0.1"}
    assert get_client_ip(headers, None) == "203.0.113.1"


# ---------------------------------------------------------------------------
# geo_service.lookup_city — private IP returns None, no network
# ---------------------------------------------------------------------------

def test_lookup_city_private_ip_returns_none():
    from security.geo_service import lookup_city
    assert lookup_city("127.0.0.1") is None
    assert lookup_city("192.168.1.1") is None
    assert lookup_city("10.0.0.5") is None


def test_lookup_city_none_returns_none():
    from security.geo_service import lookup_city
    assert lookup_city(None) is None


def test_lookup_city_success():
    from security.geo_service import lookup_city
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "status": "success",
        "city": "Almaty",
        "country": "Kazakhstan",
    }
    with patch("security.geo_service.httpx.get", return_value=mock_response):
        result = lookup_city("91.185.22.1")
    assert result == "Almaty, Kazakhstan"


def test_lookup_city_api_failure_returns_none():
    from security.geo_service import lookup_city
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "fail"}
    with patch("security.geo_service.httpx.get", return_value=mock_response):
        result = lookup_city("1.2.3.4")
    assert result is None


def test_lookup_city_network_error_returns_none():
    from security.geo_service import lookup_city
    with patch("security.geo_service.httpx.get", side_effect=Exception("timeout")):
        result = lookup_city("1.2.3.4")
    assert result is None


# ---------------------------------------------------------------------------
# LoginEventLogger.log_login
# ---------------------------------------------------------------------------

def _make_logger() -> tuple[LoginEventLogger, MagicMock]:
    db = MagicMock()
    session = MagicMock()
    db.session = session
    logger = LoginEventLogger(database=db)
    return logger, session


def test_log_login_writes_fraud_event():
    logger, session = _make_logger()
    user_id = uuid4()

    with patch("security.login_event_logger.lookup_city", return_value="Almaty, Kazakhstan"), \
         patch("security.login_event_logger.FraudEventRepository") as MockRepo:
        mock_repo = MockRepo.return_value
        logger.log_login(user_id=user_id, ip="91.185.22.1", user_agent="TestAgent/1.0")

    MockRepo.assert_called_once_with(session)
    mock_repo.log_event.assert_called_once()
    call_kwargs = mock_repo.log_event.call_args[1]
    assert call_kwargs["event_type"] == "login_success"
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["ip_address"] == "91.185.22.1"
    assert call_kwargs["metadata"]["city"] == "Almaty, Kazakhstan"
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_log_login_never_raises_on_db_error():
    logger, session = _make_logger()
    session.commit.side_effect = Exception("DB down")

    with patch("security.login_event_logger.lookup_city", return_value=None), \
         patch("security.login_event_logger.FraudEventRepository"):
        # Must not raise
        logger.log_login(user_id=uuid4(), ip="1.2.3.4", user_agent=None)


def test_log_failed_login_sets_event_type():
    logger, session = _make_logger()

    with patch("security.login_event_logger.lookup_city", return_value=None), \
         patch("security.login_event_logger.FraudEventRepository") as MockRepo:
        mock_repo = MockRepo.return_value
        logger.log_failed_login(login_identifier="+77071234567", ip="1.2.3.4", user_agent=None)

    call_kwargs = mock_repo.log_event.call_args[1]
    assert call_kwargs["event_type"] == "login_failed"
    assert call_kwargs["risk_score"] == 20
