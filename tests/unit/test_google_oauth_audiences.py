"""Google OAuth multi-audience verification.

Backend has 3 OAuth client IDs (web, android, ios). Each platform's
id_token is signed with `aud` matching that platform's client_id, and
verify_id_token must accept any of the trusted set but reject anything
else (e.g. a token from a different Google project).

Pure logic test — we mock google_id_token.verify_oauth2_token (which
does the real RSA signature check + JWKS) and assert that audience
validation routing in our code is correct.
"""

from unittest.mock import patch

import pytest

from clients.google.client import GoogleOAuthClient
from clients.google.settings import GoogleOAuthSettings


def _make_settings(android_id: str | None = None, ios_id: str | None = None) -> GoogleOAuthSettings:
    return GoogleOAuthSettings(
        client_id="WEB-CLIENT.apps.googleusercontent.com",
        client_secret="dummy",
        redirect_uri="https://api.aima.kz/auth/oauth/google/callback",
        frontend_redirect="kz.aima.aima://oauth2redirect",
        android_client_id=android_id,
        ios_client_id=ios_id,
    )


def test_trusted_audiences_includes_all_configured_client_ids():
    s = _make_settings(android_id="ANDROID-CLIENT.apps.googleusercontent.com",
                      ios_id="IOS-CLIENT.apps.googleusercontent.com")
    assert s.trusted_audiences == [
        "WEB-CLIENT.apps.googleusercontent.com",
        "ANDROID-CLIENT.apps.googleusercontent.com",
        "IOS-CLIENT.apps.googleusercontent.com",
    ]


def test_trusted_audiences_skips_unset_mobile_client_ids():
    s = _make_settings()  # both android/ios omitted
    assert s.trusted_audiences == ["WEB-CLIENT.apps.googleusercontent.com"]


@patch("clients.google.client.google_id_token.verify_oauth2_token")
def test_verify_id_token_accepts_token_signed_for_web_client(verify_mock):
    verify_mock.return_value = {
        "aud": "WEB-CLIENT.apps.googleusercontent.com",
        "email": "user@example.com",
        "sub": "user-123",
    }
    client = GoogleOAuthClient(_make_settings(
        android_id="ANDROID-CLIENT.apps.googleusercontent.com",
    ))
    payload = client.verify_id_token("fake-jwt")
    assert payload["email"] == "user@example.com"


@patch("clients.google.client.google_id_token.verify_oauth2_token")
def test_verify_id_token_accepts_token_signed_for_android_client(verify_mock):
    verify_mock.return_value = {
        "aud": "ANDROID-CLIENT.apps.googleusercontent.com",
        "email": "android-user@example.com",
    }
    client = GoogleOAuthClient(_make_settings(
        android_id="ANDROID-CLIENT.apps.googleusercontent.com",
        ios_id="IOS-CLIENT.apps.googleusercontent.com",
    ))
    payload = client.verify_id_token("fake-jwt")
    assert payload["email"] == "android-user@example.com"


@patch("clients.google.client.google_id_token.verify_oauth2_token")
def test_verify_id_token_rejects_token_signed_for_unknown_client(verify_mock):
    """Critical: a token signed for someone else's Google project must NOT
    pass our backend's verification, even if Google itself signed it."""
    verify_mock.return_value = {
        "aud": "ATTACKER-CLIENT.apps.googleusercontent.com",
        "email": "attacker@evil.com",
    }
    client = GoogleOAuthClient(_make_settings())
    with pytest.raises(ValueError, match="Invalid Google ID token"):
        client.verify_id_token("fake-jwt")


@patch("clients.google.client.google_id_token.verify_oauth2_token")
def test_verify_id_token_rejects_token_signed_for_disabled_mobile_client(verify_mock):
    """If we explicitly DON'T configure ios_client_id, a token claiming to
    be from iOS must be rejected — it would mean an attacker tries to slip
    a token from a deprecated/foreign iOS client into our backend."""
    verify_mock.return_value = {
        "aud": "IOS-CLIENT.apps.googleusercontent.com",
        "email": "ios-user@example.com",
    }
    client = GoogleOAuthClient(_make_settings())  # ios_client_id is None
    with pytest.raises(ValueError, match="Invalid Google ID token"):
        client.verify_id_token("fake-jwt")
