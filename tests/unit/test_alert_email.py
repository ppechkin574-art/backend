"""ResendEmailClient.send_alert_email — plain HTML/text alerts to ops.

Covers:
- Posts to Resend API with the correct payload (from, to, subject, html, text).
- Auto-derives `text` from HTML when `text` arg is None.
- Resend 4xx/5xx response is LOGGED but does NOT raise — an alert that
  fails to send must never break the request flow that triggered it.
- httpx network error is also swallowed (logged).
- _strip_html helper removes tags but keeps inner text.
- NotificationClientEmail.send_alert delegates to ResendEmailClient.

Resend HTTP calls are mocked via patching httpx.post.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from clients.notification.client import (
    NotificationClientEmail,
    ResendEmailClient,
    _strip_html,
)
from clients.notification.settings import EmailClientSettings


def _settings() -> EmailClientSettings:
    return EmailClientSettings(
        api_key="re_test_key",
        from_email="noreply@aima.kz",
        from_name="AIMA",
    )


def _mock_resend_ok():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"id":"resend-12345"}'
    return resp


def _mock_resend_error(code: int = 422):
    resp = MagicMock()
    resp.status_code = code
    resp.text = f"Some Resend rejection (code={code})"
    return resp


# ─────────────────────────── happy path ───────────────────────────


def test_send_alert_email_posts_to_resend_api():
    client = ResendEmailClient(_settings())

    with patch("clients.notification.client.httpx.post", return_value=_mock_resend_ok()) as mock:
        client.send_alert_email(
            to="ops@example.com",
            subject="[AIMA] cap exceeded",
            html="<h1>hi</h1><p>body</p>",
            text="hi\nbody",
        )

    assert mock.call_count == 1
    args, kwargs = mock.call_args
    assert args[0] == "https://api.resend.com/emails"
    payload = kwargs["json"]
    assert payload["from"] == "AIMA <noreply@aima.kz>"
    assert payload["to"] == ["ops@example.com"]
    assert payload["subject"] == "[AIMA] cap exceeded"
    assert payload["html"] == "<h1>hi</h1><p>body</p>"
    assert payload["text"] == "hi\nbody"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"


def test_send_alert_email_derives_text_from_html_when_text_omitted():
    """Most alert callers pass HTML only — we strip tags for the text
    fallback so the plain-text recipient still sees something readable."""
    client = ResendEmailClient(_settings())

    with patch("clients.notification.client.httpx.post", return_value=_mock_resend_ok()) as mock:
        client.send_alert_email(
            to="ops@example.com",
            subject="hi",
            html="<h1>Alert</h1><p>line1</p>",
        )

    payload = mock.call_args.kwargs["json"]
    assert "Alert" in payload["text"]
    assert "line1" in payload["text"]
    # No raw tags in the text fallback
    assert "<h1>" not in payload["text"]


# ─────────────────────────── failure handling ───────────────────────────


def test_send_alert_email_swallows_4xx_response():
    """Resend rejection (rate-limit, invalid recipient, etc.) must not
    bubble up — the SMS cap alert is best-effort, the request that
    triggered it (e.g. cap exceeded) has already returned its real
    HTTP status."""
    client = ResendEmailClient(_settings())

    with patch("clients.notification.client.httpx.post", return_value=_mock_resend_error(422)):
        # Must NOT raise
        client.send_alert_email(
            to="ops@example.com",
            subject="hi",
            html="<p>x</p>",
        )


def test_send_alert_email_swallows_5xx_response():
    client = ResendEmailClient(_settings())

    with patch("clients.notification.client.httpx.post", return_value=_mock_resend_error(503)):
        client.send_alert_email(
            to="ops@example.com",
            subject="hi",
            html="<p>x</p>",
        )


def test_send_alert_email_swallows_network_error():
    """Resend's domain unreachable / DNS failure during a Railway-side
    network blip must not crash the route."""
    client = ResendEmailClient(_settings())

    with patch(
        "clients.notification.client.httpx.post",
        side_effect=httpx.ConnectError("DNS failure"),
    ):
        # Must NOT raise
        client.send_alert_email(
            to="ops@example.com",
            subject="hi",
            html="<p>x</p>",
        )


# ─────────────────────────── _strip_html helper ───────────────────────────


def test_strip_html_removes_simple_tags():
    assert _strip_html("<p>hello</p>") == "hello"


def test_strip_html_removes_nested_tags():
    assert _strip_html("<div><b>bold</b> and <i>italic</i></div>") == "bold and italic"


def test_strip_html_handles_attributes():
    assert _strip_html('<a href="https://x.y">link</a>') == "link"


def test_strip_html_preserves_text_between_tags():
    assert _strip_html("before<br>after") == "beforeafter"


def test_strip_html_returns_empty_on_pure_tags():
    assert _strip_html("<br><hr><br/>") == ""


def test_strip_html_returns_input_unchanged_when_no_tags():
    assert _strip_html("plain text only") == "plain text only"


# ─────────────────────────── NotificationClientEmail.send_alert wrapper ───────────────────────────


def test_notification_client_email_send_alert_delegates_to_resend():
    """NotificationClientEmail.send_alert is the public delegate used
    by the sms_quota middleware so callers don't poke at the inner
    ResendEmailClient directly."""
    wrapper = NotificationClientEmail(_settings())

    with patch.object(wrapper.email_client, "send_alert_email") as mock:
        wrapper.send_alert(
            to="ops@example.com",
            subject="hi",
            html="<p>body</p>",
            text="body",
        )

    mock.assert_called_once_with(
        to="ops@example.com",
        subject="hi",
        html="<p>body</p>",
        text="body",
    )
