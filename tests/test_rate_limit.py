"""Rate-limit smoke — verifies slowapi is wired and per-IP.

Burns through the /auth/code/request 1/min budget then expects 429.
Splits into a separate test module so the rate-limit reset window
(~65s) doesn't bleed into other tests.
"""

from tests.conftest import wait_for_rate_limit_reset


def test_code_request_rate_limit_kicks_in_after_first_call(http):
    # Pre-clean: wait one window to make sure our test starts with a fresh budget.
    wait_for_rate_limit_reset()

    payload = {
        "contact": "+77001234567",
        "platform": "sms",
        "action": "register",
    }

    first = http.post("/auth/code/request", json=payload)
    assert first.status_code == 200, (
        f"first call should pass through, got {first.status_code}: {first.text}"
    )

    second = http.post("/auth/code/request", json=payload)
    assert second.status_code == 429, (
        f"second call within the same minute should be rate-limited, "
        f"got {second.status_code}: {second.text}"
    )
