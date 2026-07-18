"""Admin cache flush — guarded by Depends(allow_read_or_admin_write) (write path, admin/manager only).

Verifies the auth boundary: anonymous → 401, admin token → 200.
"""


def test_cache_flush_anon_is_unauthorized(http):
    resp = http.post("/admin/cache/flush")
    assert resp.status_code == 401


def test_cache_flush_admin_succeeds(http, admin_token):
    resp = http.post(
        "/admin/cache/flush", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["flushed"] is True
