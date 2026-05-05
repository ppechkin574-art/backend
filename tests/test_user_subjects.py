"""/user/subjects — content from Roman's prod dump (12 subjects)."""


def test_user_subjects_returns_dump_contents(http, mobile_credentials):
    import time

    from tests.conftest import wait_for_rate_limit_reset

    login, password = mobile_credentials
    # Login first; account for rate-limit collisions.
    time.sleep(13)
    auth = http.post("/auth/login", json={"login": login, "password": password})
    if auth.status_code == 429:
        wait_for_rate_limit_reset()
        auth = http.post("/auth/login", json={"login": login, "password": password})
    auth.raise_for_status()
    token = auth.json()["access_token"]

    resp = http.get("/user/subjects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    # Roman's content dump has exactly 12 subjects.
    assert body["count"] == 12
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 12

    # Each subject has the contract our mobile app expects.
    sample = body["data"][0]
    assert "id" in sample
    assert "name" in sample
    assert "type" in sample
    assert "image" in sample  # may be empty string for missing image, but must be str
    assert isinstance(sample["image"], str)

    # Image, if present, must be an absolute URL (relative path bug regression).
    if sample["image"]:
        assert sample["image"].startswith("http"), (
            f"Subject image URL must be absolute, got {sample['image']!r}"
        )
