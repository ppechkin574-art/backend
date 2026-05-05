"""Shared fixtures for smoke tests.

Tests run against a live backend (default: Railway prod). Override with
BASE_URL env var for local. Same for admin/mobile credentials.

These are smoke tests — they hit real endpoints and exercise the real
integration chain (Keycloak, Postgres, Redis, MinIO). They are NOT
isolated unit tests; expect some side-effects (SMSC DEBUG codes
written to logs, Keycloak sessions left behind).
"""

import os
import time

import httpx
import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("BASE_URL", "https://backend-production-f2a1.up.railway.app").rstrip("/")


@pytest.fixture(scope="session")
def admin_credentials() -> tuple[str, str]:
    pw = os.getenv("TEST_ADMIN_PASSWORD")
    if not pw:
        pytest.skip(
            "TEST_ADMIN_PASSWORD not set — admin-token-dependent tests skipped. "
            "Set as GitHub Actions secret (repo settings) for full coverage."
        )
    return (
        os.getenv("TEST_ADMIN_LOGIN", "admin@aima.kz"),
        pw,
    )


@pytest.fixture(scope="session")
def mobile_credentials() -> tuple[str, str]:
    return (
        os.getenv("TEST_MOBILE_LOGIN", "+77001234567"),
        os.getenv("TEST_MOBILE_PASSWORD", "Test12345!"),
    )


@pytest.fixture(scope="session")
def http(base_url: str) -> httpx.Client:
    """Plain HTTP client. Each test should manage its own rate-limit windows."""
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        yield client


@pytest.fixture(scope="session")
def admin_token(http: httpx.Client, admin_credentials: tuple[str, str]) -> str:
    """Cached admin access_token across the whole test session."""
    login, password = admin_credentials
    resp = http.post("/auth/login", json={"login": login, "password": password})
    if resp.status_code == 429:
        # We've seen this if a recent test run consumed the 5/min budget.
        # Wait one window and retry once.
        time.sleep(65)
        resp = http.post("/auth/login", json={"login": login, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def wait_for_rate_limit_reset(seconds: int = 65) -> None:
    """Helper: pause for one rate-limit minute window. Used between tests
    that intentionally exhaust limits.
    """
    time.sleep(seconds)
