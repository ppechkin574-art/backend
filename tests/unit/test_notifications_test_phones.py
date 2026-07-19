"""GET /admin/notifications/test-phones — the admin panel's Push-
уведомления page used to hardcode the phone chips shown above the
"Отправить тест" button (admin/src/pages/marketing/PushNotifications.tsx),
which drifted out of sync with the actual REVIEWER_TEST_PHONE /
DEV_RATE_LIMIT_BYPASS_PHONES env vars the backend uses for the real
POST /send-test call (CRM task "Пуш"). This endpoint exposes the real,
live-configured list so the two can never drift again.

Tests target `_get_test_phones()` directly (pure function of env vars,
no DB/FCM involved) plus the thin async wrapper endpoint.
"""

from __future__ import annotations

import asyncio

from api.routes.admin.notifications_send import _get_test_phones, get_test_phones


class TestGetTestPhones:
    def test_empty_when_no_env_set(self, monkeypatch):
        monkeypatch.delenv("REVIEWER_TEST_PHONE", raising=False)
        monkeypatch.delenv("DEV_RATE_LIMIT_BYPASS_PHONES", raising=False)
        assert _get_test_phones() == []

    def test_reads_reviewer_test_phone(self, monkeypatch):
        monkeypatch.setenv("REVIEWER_TEST_PHONE", "+77001234567")
        monkeypatch.delenv("DEV_RATE_LIMIT_BYPASS_PHONES", raising=False)
        assert _get_test_phones() == ["+77001234567"]

    def test_merges_both_env_vars_and_dedupes(self, monkeypatch):
        # Same shape as prod: REVIEWER_TEST_PHONE holds the Apple-reviewer
        # number, DEV_RATE_LIMIT_BYPASS_PHONES holds the marketing/dev
        # test numbers — combined here, in order, with de-dup.
        monkeypatch.setenv("REVIEWER_TEST_PHONE", "+77001234567")
        monkeypatch.setenv(
            "DEV_RATE_LIMIT_BYPASS_PHONES",
            "+77761888811,+77774677272,+77001234567",
        )
        assert _get_test_phones() == [
            "+77001234567",
            "+77761888811",
            "+77774677272",
        ]

    def test_strips_whitespace_and_drops_empty_entries(self, monkeypatch):
        monkeypatch.delenv("REVIEWER_TEST_PHONE", raising=False)
        monkeypatch.setenv("DEV_RATE_LIMIT_BYPASS_PHONES", " +77761888811 , , +77774677272,")
        assert _get_test_phones() == ["+77761888811", "+77774677272"]

    def test_endpoint_wraps_get_test_phones_in_response_dto(self, monkeypatch):
        monkeypatch.delenv("REVIEWER_TEST_PHONE", raising=False)
        monkeypatch.setenv("DEV_RATE_LIMIT_BYPASS_PHONES", "+77761888811,+77774677272")

        result = asyncio.run(get_test_phones())

        assert result.phones == ["+77761888811", "+77774677272"]
