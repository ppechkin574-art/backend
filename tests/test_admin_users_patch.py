"""Integration smoke tests for PATCH /admin/users/{id}.

Regression guard for the block/unblock bug fixed 2026-06-10:
  PATCH /admin/users/{id} with {"is_active": false} returned HTTP 500
  because the service raised a Pydantic ValidationError before touching
  Keycloak. After the fix, it must return 200.

Runs against the live backend (Railway prod by default).
Override target with BASE_URL environment variable.

The test user (+77001234567) is always restored to is_active=True in the
finally block so subsequent test runs and manual testing are not affected.
"""

import pytest


def _find_user_id(http, headers: dict, phone: str) -> str:
    resp = http.get("/admin/users", params={"search": phone}, headers=headers)
    assert resp.status_code == 200, f"GET /admin/users failed: {resp.status_code} {resp.text}"
    users = resp.json()
    assert users, f"Test user with phone {phone!r} not found — cannot run admin patch tests"
    return users[0]["id"]


def test_patch_is_active_false_returns_200(http, admin_token, mobile_credentials):
    """
    Regression: PATCH with only is_active=False must return 200.
    Previously crashed with 500 (Pydantic ValidationError inside the service).
    """
    phone, _ = mobile_credentials
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = _find_user_id(http, headers, phone)

    try:
        resp = http.patch(
            f"/admin/users/{user_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["is_active"] is False
    finally:
        # Always restore — keep the test user accessible for other tests.
        http.patch(
            f"/admin/users/{user_id}",
            json={"is_active": True},
            headers=headers,
        )


def test_patch_is_active_true_returns_200(http, admin_token, mobile_credentials):
    """PATCH with only is_active=True must also return 200."""
    phone, _ = mobile_credentials
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = _find_user_id(http, headers, phone)

    resp = http.patch(
        f"/admin/users/{user_id}",
        json={"is_active": True},
        headers=headers,
    )
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["is_active"] is True


def test_patch_is_active_false_then_true_roundtrip(http, admin_token, mobile_credentials):
    """Block → Unblock roundtrip: both operations succeed and state reflects correctly."""
    phone, _ = mobile_credentials
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = _find_user_id(http, headers, phone)

    try:
        block = http.patch(
            f"/admin/users/{user_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert block.status_code == 200
        assert block.json()["is_active"] is False

        unblock = http.patch(
            f"/admin/users/{user_id}",
            json={"is_active": True},
            headers=headers,
        )
        assert unblock.status_code == 200
        assert unblock.json()["is_active"] is True
    finally:
        http.patch(
            f"/admin/users/{user_id}",
            json={"is_active": True},
            headers=headers,
        )
