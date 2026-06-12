"""Service-layer tests for AuthService.login.

Verifies:
- Happy path: tokens returned from user repo are forwarded.
- UserBadCredentialsError → AuthBadCredentialsError.
- UserNotVerifiedError → AuthNotVerifiedError.

Uses lightweight fakes (no DB, no Keycloak network, no Redis). The fake
satisfies only the methods AuthService.login() actually touches.
"""

from typing import Any

import pytest

from auth.dtos.auth import AuthLoginDTO
from auth.exceptions import (
    AuthBadCredentialsError,
    AuthNotVerifiedError,
    UserBadCredentialsError,
    UserNotVerifiedError,
)
from auth.services import AuthService
from clients.identity_provider.dtos import KeycloakAccessTokenDTO


class _FakeUserRepo:
    def __init__(self, *, on_create_tokens=None):
        self._on_create_tokens = on_create_tokens or (lambda *args, **kwargs: None)
        self.create_tokens_calls: list[tuple] = []

    def create_tokens(self, login: str, password: str) -> KeycloakAccessTokenDTO:
        self.create_tokens_calls.append((login, password))
        return self._on_create_tokens(login, password)

    # AuthService.login does not touch the rest of the repo interface.
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"AuthService.login should not call _users.{name}")


def _make_service(users) -> AuthService:
    """AuthService init takes 10 collaborators, but login only needs 'users'."""
    return AuthService(
        users=users,
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
        identity_provider=None,
    )


VALID_TOKENS = KeycloakAccessTokenDTO.model_validate(
    {
        "access_token": "acc-jwt",
        "refresh_token": "ref-jwt",
        "expires_in": 300,
        "refresh_expires_in": 86400,
        "token_type": "Bearer",
        "id_token": "id-jwt",
        "not-before-policy": 0,
        "session_state": "sess",
        "scope": "openid email profile",
    }
)


def test_login_happy_path_returns_session_dto_with_both_tokens():
    repo = _FakeUserRepo(on_create_tokens=lambda *_: VALID_TOKENS)
    svc = _make_service(repo)

    session = svc.login(AuthLoginDTO(login="+77001234567", password="hunter2"))

    assert session.access_token == "acc-jwt"
    assert session.refresh_token == "ref-jwt"
    assert repo.create_tokens_calls == [("+77001234567", "hunter2")]


def test_login_translates_bad_credentials_to_auth_bad_credentials_error():
    def _raise(*_):
        raise UserBadCredentialsError

    repo = _FakeUserRepo(on_create_tokens=_raise)
    svc = _make_service(repo)

    with pytest.raises(AuthBadCredentialsError):
        svc.login(AuthLoginDTO(login="+77001234567", password="wrong"))


def test_login_translates_not_verified_to_auth_not_verified_error():
    def _raise(*_):
        raise UserNotVerifiedError

    repo = _FakeUserRepo(on_create_tokens=_raise)
    svc = _make_service(repo)

    with pytest.raises(AuthNotVerifiedError):
        svc.login(AuthLoginDTO(login="+77001234567", password="hunter2"))


def test_login_does_not_swallow_unrelated_exceptions():
    """E.g. network error from Keycloak should bubble up untouched —
    we only translate the two domain errors above."""

    class _OopsNetwork(Exception):
        pass

    def _raise(*_):
        raise _OopsNetwork("DNS fail")

    repo = _FakeUserRepo(on_create_tokens=_raise)
    svc = _make_service(repo)

    with pytest.raises(_OopsNetwork):
        svc.login(AuthLoginDTO(login="+77001234567", password="x"))
