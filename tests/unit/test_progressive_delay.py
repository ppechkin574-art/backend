"""Progressive delay on wrong /code/check attempts.

Covers:
- 1st wrong attempt → sleeps 2 seconds.
- 2nd wrong attempt → sleeps 5 seconds.
- 3rd wrong attempt → code deleted, NO sleep (already locked).
- Correct code → no delay.
- Expired code → no delay (returns False fast).
- time.sleep called from inside the sync service method; we mock it.

The check_code method has a lot of collaborators (Redis, repo,
identity provider). We use a thin fake confirmation-code repo and
inject a stub redis object that only implements what check_code
touches.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from auth.dtos.confirmation_codes import (
    ConfirmationCodeAction,
    ConfirmationCodeCreateDTO,
    ConfirmationCodeDTO,
)
from auth.services import AuthService


# ─────────────────────────── fakes ───────────────────────────


class _FakeRedis:
    def __init__(self, code: int):
        self.code = code
        self.incorrect_count = 0
        self.deleted = False
        self.verified = False

    def hget(self, _id: str, field: str):
        if field == "code":
            return str(self.code).encode()
        if field == "incorrect_count":
            return str(self.incorrect_count).encode()
        if field == "verified":
            return b"true" if self.verified else b"false"
        return None

    def hset(self, _id: str, field: str, value):
        if field == "incorrect_count":
            self.incorrect_count = int(value)
        elif field == "verified":
            self.verified = value == "true"


class _FakeConfirmationCodes:
    """Just enough surface for check_code()."""

    def __init__(self, registration_id: UUID, code: int, action: ConfirmationCodeAction):
        self.id = uuid4()
        self.registration_id = registration_id
        self.code = code
        self.action = action
        self.expires_at = datetime.now(UTC) + timedelta(minutes=10)
        self._redis = _FakeRedis(code)
        self.delete_calls: list[Any] = []

    def get(self, query):
        return ConfirmationCodeDTO(
            id=self.id,
            registration_id=self.registration_id,
            user_id=None,
            contact="+77787943760",
            code=self.code,
            correct=False,
            incorrect_count=self._redis.incorrect_count,
            action=self.action,
            expires_at=self.expires_at,
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    def delete(self, code_id):
        self.delete_calls.append(code_id)


def _make_service(code: int, action: ConfirmationCodeAction):
    """Service with only confirmation_codes wired; everything else is
    None and check_code doesn't touch it."""
    repo = _FakeConfirmationCodes(uuid4(), code, action)
    service = AuthService(
        users=None,
        confirmation_codes=repo,
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
    return service, repo


# ─────────────────────────── delay matrix ───────────────────────────


def test_correct_code_returns_true_with_no_sleep():
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)

    with patch("auth.services.time.sleep") as mock_sleep:
        result = service.check_code(
            repo.registration_id, 123456, ConfirmationCodeAction.REGISTER
        )

    assert result is True
    mock_sleep.assert_not_called()
    assert repo._redis.verified is True


def test_first_wrong_attempt_sleeps_2_seconds():
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)

    with patch("auth.services.time.sleep") as mock_sleep:
        result = service.check_code(
            repo.registration_id, 999999, ConfirmationCodeAction.REGISTER
        )

    assert result is False
    mock_sleep.assert_called_once_with(2)
    assert repo._redis.incorrect_count == 1
    # Code NOT deleted yet — under MAX_ATTEMPTS (3)
    assert repo.delete_calls == []


def test_second_wrong_attempt_sleeps_5_seconds():
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)
    # Simulate one prior wrong attempt
    repo._redis.incorrect_count = 1

    with patch("auth.services.time.sleep") as mock_sleep:
        result = service.check_code(
            repo.registration_id, 999999, ConfirmationCodeAction.REGISTER
        )

    assert result is False
    mock_sleep.assert_called_once_with(5)
    assert repo._redis.incorrect_count == 2
    assert repo.delete_calls == []


def test_third_wrong_attempt_deletes_code_and_no_sleep():
    """At MAX_ATTEMPTS we delete the code and refuse further checks —
    delay would be pointless since there's nothing left to guess."""
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)
    # Simulate two prior wrong attempts
    repo._redis.incorrect_count = 2

    with patch("auth.services.time.sleep") as mock_sleep:
        result = service.check_code(
            repo.registration_id, 999999, ConfirmationCodeAction.REGISTER
        )

    assert result is False
    mock_sleep.assert_not_called()
    assert len(repo.delete_calls) == 1


def test_expired_code_returns_false_without_delay():
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)
    repo.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with patch("auth.services.time.sleep") as mock_sleep:
        result = service.check_code(
            repo.registration_id, 123456, ConfirmationCodeAction.REGISTER
        )

    assert result is False
    mock_sleep.assert_not_called()


def test_delay_progression_is_linear_2_then_5():
    """Sequence of two wrong attempts gives 2s then 5s — verifies the
    `2 if new_count == 1 else 5` branch."""
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)

    with patch("auth.services.time.sleep") as mock_sleep:
        # 1st wrong
        service.check_code(
            repo.registration_id, 111111, ConfirmationCodeAction.REGISTER
        )
        # 2nd wrong
        service.check_code(
            repo.registration_id, 222222, ConfirmationCodeAction.REGISTER
        )

    assert mock_sleep.call_count == 2
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [2, 5]


def test_attempt_counter_persists_across_calls():
    """After 3 wrong attempts back-to-back, the code is gone — the
    counter has to actually persist (we keep it in Redis HSET)."""
    service, repo = _make_service(code=123456, action=ConfirmationCodeAction.REGISTER)

    with patch("auth.services.time.sleep"):  # silence the sleeps
        for _ in range(3):
            service.check_code(
                repo.registration_id, 999999, ConfirmationCodeAction.REGISTER
            )

    # After 3 misses code is deleted
    assert len(repo.delete_calls) == 1
    # And incorrect_count reached 3
    assert repo._redis.incorrect_count == 3
