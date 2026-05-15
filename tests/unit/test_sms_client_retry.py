"""SMSCClient: translit=1, sender fallback, retry-on-Error-8.

Covers:
- _build_payload always carries `translit=1` (Cyrillic OTPs route through
  the operator-approved transliterated path).
- _build_payload drops the `sender` field when None or empty.
- send_sms primary call uses the configured sender.
- send_sms retries with empty sender on Error 8 ("can't to deliver").
- send_sms does NOT retry on auth/balance/format errors (Errors 2/3/4/7).
- The legacy default `SMSC.KZ` sender is treated as "no sender" — that
  exact value is what caused Tele2/Altel to refuse delivery before the
  договор был активирован, so any explicit `SMSC.KZ` in env is now
  filtered to None and the SMSC default route is used.
- Phone normalization: +7 prefix, 8 prefix, leading-7 ten-digit, etc.

We mock _make_request so tests don't hit SMSC.kz network.
"""

from unittest.mock import MagicMock, patch

import pytest

from clients.notification.settings import SMSCSettings
from clients.notification.sms_client import SMSCClient


def _settings(sender: str | None = "AIMA", debug: bool = False) -> SMSCSettings:
    return SMSCSettings(login="aima_app", key="secret", sender=sender, debug=debug)


# ─────────────────────────── normalize_phone ───────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+77787943760", "77787943760"),
        ("87787943760", "77787943760"),
        ("77787943760", "77787943760"),
        ("7787943760", "77787943760"),  # 10 digits starting with 7
        ("8 (778) 794-37-60", "77787943760"),
        ("+7 (778) 794 37 60", "77787943760"),
    ],
)
def test_normalize_phone_handles_common_kz_formats(raw, expected):
    client = SMSCClient(_settings())
    assert client.normalize_phone(raw) == expected


# ─────────────────────────── _build_payload ───────────────────────────


def test_build_payload_always_carries_translit_1():
    """Without translit, Tele2/Altel rejects Cyrillic transactional SMS
    with Error 8. Always-on is the only safe setting until we have a
    per-operator strategy."""
    client = SMSCClient(_settings())
    payload = client._build_payload("77787943760", "Код: 1234", "AIMA")
    assert payload["translit"] == 1


def test_build_payload_includes_sender_when_provided():
    client = SMSCClient(_settings())
    payload = client._build_payload("77787943760", "Код: 1234", "AIMA")
    assert payload["sender"] == "AIMA"


def test_build_payload_omits_sender_field_when_none():
    """Empty sender → SMSC routes via account default short-number."""
    client = SMSCClient(_settings())
    payload = client._build_payload("77787943760", "Код: 1234", None)
    assert "sender" not in payload


def test_build_payload_omits_sender_field_when_empty_string():
    client = SMSCClient(_settings())
    payload = client._build_payload("77787943760", "Код: 1234", "")
    assert "sender" not in payload


def test_build_payload_has_utf8_charset():
    """Cyrillic-safe charset must be set even though translit kicks in
    on SMSC side — translit only fires when charset is honoured."""
    client = SMSCClient(_settings())
    payload = client._build_payload("77787943760", "Код: 1234", "AIMA")
    assert payload["charset"] == "utf-8"


# ─────────────────────────── send_sms happy path ───────────────────────────


def test_send_sms_uses_settings_sender_when_no_arg():
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"id": 1, "cnt": 1, "cost": 23.5}
        result = client.send_sms("+77787943760", "Код подтверждения: 1234")

    assert result["id"] == 1
    args, _ = mock.call_args
    method, payload = args
    assert method == "send/"
    assert payload["sender"] == "AIMA"
    assert payload["translit"] == 1


def test_send_sms_explicit_sender_overrides_settings():
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"id": 1}
        client.send_sms("+77787943760", "msg", sender="OTHER")

    payload = mock.call_args.args[1]
    assert payload["sender"] == "OTHER"


def test_send_sms_legacy_smsc_kz_sender_is_normalized_to_none():
    """`SMSC.KZ` was the historical default before the договор; that exact
    value made Tele2/Altel refuse delivery. We now treat it as 'no sender'
    so the call routes through SMSC's default short number instead."""
    client = SMSCClient(_settings(sender="SMSC.KZ"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"id": 1}
        client.send_sms("+77787943760", "msg")

    payload = mock.call_args.args[1]
    assert "sender" not in payload


def test_send_sms_legacy_smsc_sender_also_normalized():
    client = SMSCClient(_settings(sender="SMSC"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"id": 1}
        client.send_sms("+77787943760", "msg")

    payload = mock.call_args.args[1]
    assert "sender" not in payload


def test_send_sms_rejects_non_kz_phone():
    """Договор §6.7 — штраф 500 ₸/SMS или 1М ₸ за международный трафик
    от национального имени. Defence-in-depth: client-side check before
    we even hit SMSC."""
    client = SMSCClient(_settings())
    with pytest.raises(ValueError, match="Invalid phone format"):
        client.send_sms("+15551234567", "msg")


# ─────────────────────────── retry on Error 8 ───────────────────────────


def test_send_sms_retries_with_empty_sender_on_error_8():
    """Error 8 from SMSC ("can't to deliver") for a custom sender →
    retry with no sender so SMSC routes through its default short
    number. This unblocks Tele2/Altel even when the custom sender is
    pending moderation."""
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.side_effect = [
            {"error": "can't to deliver", "error_code": 8},
            {"id": 42, "cost": 23.5},
        ]
        result = client.send_sms("+77787943760", "Код: 1234")

    assert result["id"] == 42
    assert mock.call_count == 2

    primary_payload = mock.call_args_list[0].args[1]
    fallback_payload = mock.call_args_list[1].args[1]
    assert primary_payload["sender"] == "AIMA"
    assert "sender" not in fallback_payload


def test_send_sms_does_not_retry_when_primary_sender_is_already_empty():
    """If we already used the default route on the first call, there's
    no second route to fall back to — error 8 just propagates."""
    client = SMSCClient(_settings(sender=None))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"error": "can't to deliver", "error_code": 8}
        with pytest.raises(Exception, match="SMSC error 8"):
            client.send_sms("+77787943760", "Код: 1234")

    assert mock.call_count == 1


def test_send_sms_does_not_retry_on_auth_error():
    """Error 2 (login/psw wrong, IP blocked) won't be solved by changing
    sender — short-circuit and surface the failure."""
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"error": "authorise error", "error_code": 2}
        with pytest.raises(Exception, match="SMSC error 2"):
            client.send_sms("+77787943760", "Код: 1234")

    assert mock.call_count == 1


def test_send_sms_does_not_retry_on_balance_error():
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"error": "balance is zero", "error_code": 3}
        with pytest.raises(Exception, match="SMSC error 3"):
            client.send_sms("+77787943760", "Код: 1234")

    assert mock.call_count == 1


def test_send_sms_does_not_retry_on_invalid_phone():
    client = SMSCClient(_settings(sender="AIMA"))
    with patch.object(client, "_make_request") as mock:
        mock.return_value = {"error": "invalid phone", "error_code": 7}
        with pytest.raises(Exception, match="SMSC error 7"):
            client.send_sms("+77787943760", "Код: 1234")

    assert mock.call_count == 1
