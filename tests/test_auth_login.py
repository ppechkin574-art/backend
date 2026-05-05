"""Login smoke tests.

Uses mobile_credentials (phone + password) to keep admin's rate-limit
budget free for other tests.
"""

import time

from tests.conftest import wait_for_rate_limit_reset


def test_login_with_valid_phone_credentials_returns_tokens(http, mobile_credentials):
    login, password = mobile_credentials
    resp = http.post("/auth/login", json={"login": login, "password": password})
    if resp.status_code == 429:
        wait_for_rate_limit_reset()
        resp = http.post("/auth/login", json={"login": login, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert len(body["access_token"]) > 100  # JWT is always longer


def test_login_with_invalid_password_returns_401(http, mobile_credentials):
    # Avoid 429 from the previous successful login: wait one slot.
    time.sleep(13)  # sub-window pause
    login, _ = mobile_credentials
    resp = http.post(
        "/auth/login", json={"login": login, "password": "definitely-not-the-right-pw"}
    )
    if resp.status_code == 429:
        wait_for_rate_limit_reset()
        resp = http.post(
            "/auth/login",
            json={"login": login, "password": "definitely-not-the-right-pw"},
        )
    assert resp.status_code == 401
