"""Smoke tests: mascot transform fields (scale, x, y, rotation) on onboarding steps.

Verifies the full round-trip:
  admin create → values persisted → admin read back → public API returns them.
Also pins Pydantic validation boundaries.

A single story is created at the start and deleted at the end; each test
operates on that story so we only pay the create/delete cost once.
"""

import pytest

# ─── Helpers ────────────────────────────────────────────────────────────────

STORY_PAYLOAD = {
    "name": "SMOKE_TEST_mascot_transform",
    "priority": 0,
    "is_active": False,
    "is_mandatory": False,
    "is_test": True,
    "skip_delay_seconds": 3,
    "target_audience": "ALL",
    "new_user_days": 7,
    "trigger": "FIRST_OPEN",
    "immediate_count": 1,
    "max_shows_per_user": 1,
    "start_screen": "HOME",
    "steps": [
        {
            "step_order": 1,
            "mascot_image_url": None,
            "title_ru": "Test step",
            "title_kk": "Test step",
            "body_ru": "body",
            "body_kk": "body",
            "mascot_position": "bottom_left",
            "spotlight_element_key": None,
            "action_label_ru": None,
            "action_label_kk": None,
            "action_route": None,
            "mascot_scale": 1.5,
            "mascot_x": 20.0,
            "mascot_y": -10.0,
            "mascot_rotation": 15.0,
        }
    ],
}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def story_id(http, admin_token):
    """Create a test story, yield its id, delete it afterwards."""
    resp = http.post(
        "/admin/onboarding/stories",
        json=STORY_PAYLOAD,
        headers=auth(admin_token),
    )
    assert resp.status_code in (200, 201), f"Create failed: {resp.text}"
    sid = resp.json()["id"]
    yield sid
    http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── Create / read-back ──────────────────────────────────────────────────────

def test_create_persists_mascot_scale(http, admin_token, story_id):
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    assert resp.status_code == 200
    step = resp.json()["steps"][0]
    assert abs(step["mascot_scale"] - 1.5) < 1e-6, f"Expected 1.5, got {step['mascot_scale']}"


def test_create_persists_mascot_x(http, admin_token, story_id):
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert abs(step["mascot_x"] - 20.0) < 1e-6, f"Expected 20.0, got {step['mascot_x']}"


def test_create_persists_mascot_y(http, admin_token, story_id):
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert abs(step["mascot_y"] - (-10.0)) < 1e-6, f"Expected -10.0, got {step['mascot_y']}"


def test_create_persists_mascot_rotation(http, admin_token, story_id):
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert abs(step["mascot_rotation"] - 15.0) < 1e-6, f"Expected 15.0, got {step['mascot_rotation']}"


# ─── Update / re-read ────────────────────────────────────────────────────────

def test_update_mascot_transform_persists(http, admin_token, story_id):
    """Patch story with new transform values, confirm they come back correctly."""
    new_steps = [
        {
            "step_order": 1,
            "mascot_image_url": None,
            "title_ru": "Test step",
            "title_kk": "Test step",
            "body_ru": "body",
            "body_kk": "body",
            "mascot_position": "bottom_right",
            "spotlight_element_key": None,
            "action_label_ru": None,
            "action_label_kk": None,
            "action_route": None,
            "mascot_scale": 0.75,
            "mascot_x": -50.0,
            "mascot_y": 30.0,
            "mascot_rotation": -45.0,
        }
    ]
    patch = http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"steps": new_steps},
        headers=auth(admin_token),
    )
    assert patch.status_code == 200, f"Update failed: {patch.text}"

    get = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = get.json()["steps"][0]

    assert abs(step["mascot_scale"] - 0.75) < 1e-6
    assert abs(step["mascot_x"] - (-50.0)) < 1e-6
    assert abs(step["mascot_y"] - 30.0) < 1e-6
    assert abs(step["mascot_rotation"] - (-45.0)) < 1e-6


# ─── Defaults ───────────────────────────────────────────────────────────────

def test_defaults_when_fields_omitted(http, admin_token):
    """A step created without transform fields should get scale=1, x/y/rot=0."""
    payload = {**STORY_PAYLOAD, "name": "SMOKE_TEST_transform_defaults"}
    step_no_transform = {k: v for k, v in STORY_PAYLOAD["steps"][0].items()
                         if k not in ("mascot_scale", "mascot_x", "mascot_y", "mascot_rotation")}
    payload = {**payload, "steps": [step_no_transform]}

    resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
    assert resp.status_code in (200, 201), resp.text
    sid = resp.json()["id"]

    get = http.get(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))
    step = get.json()["steps"][0]

    http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    assert abs(step["mascot_scale"] - 1.0) < 1e-6
    assert abs(step["mascot_x"]) < 1e-6
    assert abs(step["mascot_y"]) < 1e-6
    assert abs(step["mascot_rotation"]) < 1e-6


# ─── Public API ──────────────────────────────────────────────────────────────

def test_public_api_returns_transform_fields(http, admin_token, story_id, mobile_credentials):
    """Activate the story, hit mobile /onboarding/stories, verify transform fields in public DTO."""
    # Get mobile user token
    login, password = mobile_credentials
    token_resp = http.post("/auth/login", json={"login": login, "password": password})
    if token_resp.status_code != 200:
        pytest.skip(f"Mobile login failed ({token_resp.status_code}) — skipping public DTO check")
    user_token = token_resp.json()["access_token"]

    http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"is_active": True},
        headers=auth(admin_token),
    )
    try:
        resp = http.get("/onboarding/stories", headers=auth(user_token))
        assert resp.status_code == 200, resp.text
        stories = resp.json()
        # Check schema on any story that has steps
        stories_with_steps = [s for s in stories if s.get("steps")]
        if not stories_with_steps:
            pytest.skip("No stories with steps returned for this user — cannot verify schema")
        step = stories_with_steps[0]["steps"][0]
        assert "mascot_scale" in step, "mascot_scale missing from public DTO"
        assert "mascot_x" in step, "mascot_x missing from public DTO"
        assert "mascot_y" in step, "mascot_y missing from public DTO"
        assert "mascot_rotation" in step, "mascot_rotation missing from public DTO"
    finally:
        http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"is_active": False},
            headers=auth(admin_token),
        )


# ─── Validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("mascot_scale", 0.0),    # below min 0.3
    ("mascot_scale", 5.0),    # above max 3.0
    ("mascot_x", -201.0),     # below min -200
    ("mascot_x", 201.0),      # above max 200
    ("mascot_y", -201.0),
    ("mascot_y", 201.0),
    ("mascot_rotation", -181.0),
    ("mascot_rotation", 181.0),
])
def test_validation_rejects_out_of_range(http, admin_token, field, value):
    """Pydantic should reject out-of-range transform values with 422."""
    bad_step = {**STORY_PAYLOAD["steps"][0], field: value}
    payload = {**STORY_PAYLOAD, "name": f"SMOKE_invalid_{field}", "steps": [bad_step]}
    resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
    assert resp.status_code == 422, (
        f"Expected 422 for {field}={value}, got {resp.status_code}: {resp.text}"
    )
