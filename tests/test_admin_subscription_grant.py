"""Admin grant/revoke PRO subscription — guarded by Depends(allow_read_or_admin_write) (write path, admin/manager only).

Smoke test: verify auth boundary on both new endpoints.

Note: the actual grant/revoke roundtrip is NOT exercised here because
that would mutate prod Keycloak state for whatever user UUID we'd pass.
Auth-boundary (anon 401 / admin reaches handler) is the relevant
regression to pin — the service-layer logic for grant is small enough
that a manual run on a throwaway test user is the right verification.
"""

import uuid


def test_grant_pro_anon_is_unauthorized(http):
    fake_user_id = uuid.uuid4()
    resp = http.post(
        f"/admin/users/{fake_user_id}/grant-pro-subscription",
        json={"days": 30},
    )
    assert resp.status_code == 401


def test_grant_pro_rejects_zero_days(http, admin_token):
    fake_user_id = uuid.uuid4()
    resp = http.post(
        f"/admin/users/{fake_user_id}/grant-pro-subscription",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"days": 0},
    )
    # Pydantic validation rejects with 422
    assert resp.status_code == 422


def test_grant_pro_rejects_negative_days(http, admin_token):
    fake_user_id = uuid.uuid4()
    resp = http.post(
        f"/admin/users/{fake_user_id}/grant-pro-subscription",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"days": -7},
    )
    assert resp.status_code == 422


def test_grant_pro_rejects_excessive_days(http, admin_token):
    """Pydantic Field has le=3650 (~10 years). Above that → 422.

    Pins the upper bound — accidental `days=999999` shouldn't slip
    through (would set subscription_end far enough that audit/
    refund logic might choke on the date).
    """
    fake_user_id = uuid.uuid4()
    resp = http.post(
        f"/admin/users/{fake_user_id}/grant-pro-subscription",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"days": 1_000_000},
    )
    assert resp.status_code == 422


def test_reset_subscription_anon_is_unauthorized(http):
    """Sister endpoint — confirm same boundary still holds after we
    added grant. Regression guard against accidentally removing the
    `Depends(allow_read_or_admin_write)` from the router."""
    fake_user_id = uuid.uuid4()
    resp = http.post(f"/admin/users/{fake_user_id}/reset-subscription")
    assert resp.status_code == 401
