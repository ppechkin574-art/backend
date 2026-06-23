"""Unit tests for the new-login security push (LoginAlertService) and its
wiring into AuthService._send_login_alert.

Proves the functional contract WITHOUT a real Firebase/device:
- when the user has registered FCM tokens → exactly one multicast is sent with
  the right title/body/data and those tokens;
- when there are no tokens → nothing is sent (and it's logged, not silent);
- when Firebase is disabled → no DB query, no send;
- failures never propagate into the login flow;
- AuthService resolves the user's sub from the access token and forwards it,
  is None-safe, and swallows errors.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from auth.login_alert_service import LoginAlertService
from auth.services import AuthService


def _make_alert(enabled=True, tokens=None):
    tokens = tokens or []
    firebase = MagicMock()
    firebase.enabled = enabled
    firebase.send_multicast.return_value = SimpleNamespace(
        requested=len(tokens), success=len(tokens), failure=0
    )
    database = MagicMock()
    session = MagicMock()
    session.scalars.return_value.all.return_value = tokens
    database.session = session
    svc = LoginAlertService(database=database, firebase_client=firebase)
    return svc, firebase, session


def test_sends_one_multicast_with_correct_payload_to_registered_tokens():
    svc, firebase, _ = _make_alert(enabled=True, tokens=["tokA", "tokB"])

    svc.notify_new_login(uuid4())

    firebase.send_multicast.assert_called_once()
    args, kwargs = firebase.send_multicast.call_args
    assert args[0] == ["tokA", "tokB"]  # tokens passed positionally
    assert kwargs["title"] == LoginAlertService._TITLE
    assert kwargs["body"] == LoginAlertService._BODY
    assert kwargs["data"] == {"type": "new_login"}


def test_no_registered_tokens_does_not_send():
    svc, firebase, _ = _make_alert(enabled=True, tokens=[])

    svc.notify_new_login(uuid4())

    firebase.send_multicast.assert_not_called()


def test_disabled_firebase_skips_db_and_send():
    # Even with tokens present, a disabled client must short-circuit before
    # touching the DB (keeps the login path cheap while dormant).
    svc, firebase, session = _make_alert(enabled=False, tokens=["tokA"])

    svc.notify_new_login(uuid4())

    session.scalars.assert_not_called()
    firebase.send_multicast.assert_not_called()


def test_send_failure_never_raises():
    svc, firebase, _ = _make_alert(enabled=True, tokens=["tokA"])
    firebase.send_multicast.side_effect = RuntimeError("FCM unreachable")

    # Must swallow — a push failure can never break authentication.
    svc.notify_new_login(uuid4())


def _make_auth(login_alert, identity_provider):
    """AuthService with only the deps _send_login_alert touches; the rest are
    None (mirrors tests/unit/test_progressive_delay.py::_make_service)."""
    return AuthService(
        users=None,
        confirmation_codes=None,
        notification_client=None,
        email_client=None,
        sms_client=None,
        whatsapp_client=None,
        telegram_otp_client=None,
        redis=None,
        google_client=None,
        apple_client=None,
        oauth_helper=None,
        identity_provider=identity_provider,
        login_alert=login_alert,
    )


def test_send_login_alert_resolves_sub_and_notifies():
    sub = uuid4()
    idp = MagicMock()
    idp.get_user_sub_from_token.return_value = sub
    alert = MagicMock()
    alert.enabled = True

    _make_auth(alert, idp)._send_login_alert("access-token")

    idp.get_user_sub_from_token.assert_called_once_with("access-token")
    alert.notify_new_login.assert_called_once_with(sub)


def test_send_login_alert_none_is_safe():
    idp = MagicMock()

    _make_auth(None, idp)._send_login_alert("tok")  # must not raise

    idp.get_user_sub_from_token.assert_not_called()


def test_send_login_alert_disabled_does_not_resolve_or_notify():
    idp = MagicMock()
    alert = MagicMock()
    alert.enabled = False

    _make_auth(alert, idp)._send_login_alert("tok")

    idp.get_user_sub_from_token.assert_not_called()
    alert.notify_new_login.assert_not_called()


def test_send_login_alert_swallows_errors():
    idp = MagicMock()
    idp.get_user_sub_from_token.side_effect = RuntimeError("bad token")
    alert = MagicMock()
    alert.enabled = True

    _make_auth(alert, idp)._send_login_alert("tok")  # must not raise
