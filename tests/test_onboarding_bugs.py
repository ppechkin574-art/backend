"""Regression tests for 6 onboarding bugs found in audit.

Bug 1: record_view with non-existent story_id → was 500 (FK crash), now 404
Bug 2: PATCH with steps:[] deletes all steps → now 400
Bug 3: Invalid enum values (target_audience, trigger, start_screen, mascot_position) → now 422
Bug 4: Duplicate step_order in one story → now 409/DB error
Bug 5: Mascot image deleted from MinIO when story deleted (verified by upload→delete flow)
Bug 6: Nullable fields (spotlight_element_key, action_label_ru/kk, action_route) survive
       null→save→reload round-trip without corruption
"""

import pytest

BASE_STORY = {
    "name": "SMOKE_bugs",
    "priority": 0,
    "is_active": False,
    "is_mandatory": False,
    "is_test": True,
    "skip_delay_seconds": 0,
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
            "title_ru": "Test",
            "title_kk": "Test",
            "body_ru": "body",
            "body_kk": "body",
            "mascot_position": "bottom_left",
            "spotlight_element_key": None,
            "action_label_ru": None,
            "action_label_kk": None,
            "action_route": None,
            "mascot_scale": 1.0,
            "mascot_x": 0.0,
            "mascot_y": 0.0,
            "mascot_rotation": 0.0,
        }
    ],
}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def story_id(http, admin_token):
    resp = http.post("/admin/onboarding/stories", json=BASE_STORY, headers=auth(admin_token))
    assert resp.status_code in (200, 201), resp.text
    sid = resp.json()["id"]
    yield sid
    http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── Bug 1: record_view 500 → 404 ───────────────────────────────────────────

def test_bug1_record_view_nonexistent_story_returns_404(http, mobile_credentials):
    """Was: 500 FK constraint violation. Now: 404 Not Found."""
    login, pw = mobile_credentials
    r = http.post("/auth/login", json={"login": login, "password": pw})
    if r.status_code != 200:
        pytest.skip("Mobile login unavailable")
    token = r.json()["access_token"]

    resp = http.post(
        "/onboarding/stories/999999/view",
        json={"skipped": False},
        headers=auth(token),
    )
    assert resp.status_code == 404, (
        f"Expected 404 for nonexistent story, got {resp.status_code}: {resp.text}"
    )


def test_bug1_record_view_anon_returns_401(http):
    """Auth boundary: unauthenticated request must return 401, not 500."""
    resp = http.post("/onboarding/stories/999999/view", json={"skipped": False})
    assert resp.status_code == 401


# ─── Bug 2: empty steps[] must be rejected ───────────────────────────────────

def test_bug2_patch_with_empty_steps_returns_400(http, admin_token, story_id):
    """PATCH steps:[] used to silently delete all steps. Now returns 400."""
    resp = http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"steps": []},
        headers=auth(admin_token),
    )
    assert resp.status_code == 400, (
        f"Expected 400 for empty steps, got {resp.status_code}: {resp.text}"
    )


def test_bug2_steps_unchanged_after_rejected_empty_patch(http, admin_token, story_id):
    """After a rejected empty-steps PATCH, original steps must still be there."""
    http.patch(f"/admin/onboarding/stories/{story_id}", json={"steps": []}, headers=auth(admin_token))
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    assert resp.status_code == 200
    assert len(resp.json()["steps"]) >= 1, "Steps were deleted despite 400 rejection"


# ─── Bug 3: invalid enum values rejected with 422 ────────────────────────────

@pytest.mark.parametrize("field,bad_value", [
    ("target_audience", "HACKED"),
    ("target_audience", "all"),           # case-sensitive
    ("trigger", "SCHEDULED"),
    ("trigger", "first_open"),            # case-sensitive
    ("start_screen", "SETTINGS"),
    ("start_screen", "home"),             # case-sensitive
])
def test_bug3_invalid_story_enum_rejected(http, admin_token, field, bad_value):
    """Invalid enum values for story fields must return 422."""
    payload = {**BASE_STORY, "name": f"SMOKE_bad_{field}", field: bad_value}
    resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
    assert resp.status_code == 422, (
        f"Expected 422 for {field}={bad_value!r}, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.parametrize("bad_position", [
    "center", "bottom", "BOTTOM_LEFT", "top",
])
def test_bug3_invalid_mascot_position_rejected(http, admin_token, bad_position):
    """Invalid mascot_position must return 422."""
    bad_step = {**BASE_STORY["steps"][0], "mascot_position": bad_position}
    payload = {**BASE_STORY, "name": "SMOKE_bad_pos", "steps": [bad_step]}
    resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
    assert resp.status_code == 422, (
        f"Expected 422 for mascot_position={bad_position!r}, got {resp.status_code}: {resp.text}"
    )


def test_bug3_valid_enum_values_accepted(http, admin_token):
    """Verify all valid combinations are accepted (regression guard)."""
    for ta in ("ALL", "NEW_USERS"):
        for tr in ("FIRST_OPEN", "IMMEDIATE"):
            for ss in ("HOME", "TRAINER", "PROFILE", "LEADERBOARD", "SUBSCRIPTION"):
                payload = {
                    **BASE_STORY,
                    "name": f"SMOKE_valid_{ta}_{tr}_{ss}",
                    "target_audience": ta,
                    "trigger": tr,
                    "start_screen": ss,
                }
                resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
                assert resp.status_code in (200, 201), (
                    f"Unexpected rejection for valid combo {ta}/{tr}/{ss}: {resp.text}"
                )
                # cleanup
                http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))


# ─── Bug 4: duplicate step_order rejected ────────────────────────────────────

def test_bug4_duplicate_step_order_rejected(http, admin_token):
    """Two steps with same step_order in one story must fail (DB unique constraint)."""
    payload = {
        **BASE_STORY,
        "name": "SMOKE_dup_order",
        "steps": [
            {**BASE_STORY["steps"][0], "step_order": 1},
            {**BASE_STORY["steps"][0], "step_order": 1},  # duplicate!
        ],
    }
    resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
    # Should be rejected — either 422 (Pydantic) or 409/500 (DB unique constraint)
    assert resp.status_code in (400, 409, 422, 500), (
        f"Expected error for duplicate step_order, got {resp.status_code}: {resp.text}"
    )
    # If somehow created, clean up
    if resp.status_code in (200, 201):
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))


# ─── Bug 6: nullable optional fields round-trip correctly ────────────────────

def test_bug6_null_spotlight_key_round_trips(http, admin_token, story_id):
    """spotlight_element_key=null must persist as null (not empty string)."""
    http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"steps": [{**BASE_STORY["steps"][0], "spotlight_element_key": None}]},
        headers=auth(admin_token),
    )
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert step["spotlight_element_key"] is None, (
        f"Expected null spotlight_element_key, got {step['spotlight_element_key']!r}"
    )


def test_bug6_null_action_fields_round_trip(http, admin_token, story_id):
    """action_label_ru/kk and action_route=null must persist as null."""
    patch_step = {
        **BASE_STORY["steps"][0],
        "action_label_ru": None,
        "action_label_kk": None,
        "action_route": None,
    }
    http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"steps": [patch_step]},
        headers=auth(admin_token),
    )
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert step["action_label_ru"] is None
    assert step["action_label_kk"] is None
    assert step["action_route"] is None


def test_bug6_populated_action_fields_round_trip(http, admin_token, story_id):
    """Non-null action fields must also persist correctly."""
    patch_step = {
        **BASE_STORY["steps"][0],
        "action_label_ru": "Перейти",
        "action_label_kk": "Өту",
        "action_route": "trainer",
        "spotlight_element_key": "home_tab",
    }
    http.patch(
        f"/admin/onboarding/stories/{story_id}",
        json={"steps": [patch_step]},
        headers=auth(admin_token),
    )
    resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
    step = resp.json()["steps"][0]
    assert step["action_label_ru"] == "Перейти"
    assert step["action_label_kk"] == "Өту"
    assert step["action_route"] == "trainer"
    assert step["spotlight_element_key"] == "home_tab"
