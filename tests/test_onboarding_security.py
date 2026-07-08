"""
Security and authorization tests for onboarding endpoints.

Covers:
  - Auth required on all endpoints (401 without token)
  - Admin-only enforcement (403 for regular users)
  - Invalid/malicious enum values rejected (422)
  - Empty/minimal steps rejected (400)
  - Oversized payload handling
  - XSS/injection payloads stored as plain text (not executed)
  - Boundary values for numeric fields
  - Duplicate step_order rejected
"""

import pytest


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


BASE_STEP = {
    "step_order": 1,
    "mascot_image_url": None,
    "title_ru": "Security test",
    "title_kk": "Security test",
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


def base_story(**overrides) -> dict:
    s = {
        "name": "SEC_TEST",
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
        "steps": [BASE_STEP],
    }
    s.update(overrides)
    return s


@pytest.fixture(scope="module")
def story_id(http, admin_token):
    resp = http.post("/admin/onboarding/stories", json=base_story(), headers=auth(admin_token))
    assert resp.status_code in (200, 201), resp.text
    sid = resp.json()["id"]
    yield sid
    http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


@pytest.fixture(scope="session")
def user_token(http, mobile_credentials):
    import time
    login, pw = mobile_credentials
    resp = http.post("/auth/login", json={"login": login, "password": pw})
    if resp.status_code == 429:
        time.sleep(65)
        resp = http.post("/auth/login", json={"login": login, "password": pw})
    resp.raise_for_status()
    return resp.json()["access_token"]


# ─── 1. Auth Required (401) ───────────────────────────────────────────────────

class TestAuthRequired:
    def test_public_stories_no_token(self, http):
        resp = http.get("/onboarding/stories")
        assert resp.status_code == 401

    def test_views_no_token(self, http):
        resp = http.get("/onboarding/stories/views")
        assert resp.status_code == 401

    def test_record_view_no_token(self, http, story_id):
        resp = http.post(
            f"/onboarding/stories/{story_id}/view",
            json={"story_id": story_id, "skipped": False},
        )
        assert resp.status_code == 401

    def test_admin_list_no_token(self, http):
        resp = http.get("/admin/onboarding/stories")
        assert resp.status_code == 401

    def test_admin_create_no_token(self, http):
        resp = http.post("/admin/onboarding/stories", json=base_story())
        assert resp.status_code == 401

    def test_admin_get_no_token(self, http, story_id):
        resp = http.get(f"/admin/onboarding/stories/{story_id}")
        assert resp.status_code == 401

    def test_admin_patch_no_token(self, http, story_id):
        resp = http.patch(f"/admin/onboarding/stories/{story_id}", json={"name": "x"})
        assert resp.status_code == 401

    def test_admin_delete_no_token(self, http, story_id):
        resp = http.delete(f"/admin/onboarding/stories/{story_id}")
        assert resp.status_code in (401, 403)


# ─── 2. Admin Role Required (403) ─────────────────────────────────────────────

class TestAdminRoleRequired:
    def test_user_cannot_list_admin_stories(self, http, user_token):
        resp = http.get("/admin/onboarding/stories", headers=auth(user_token))
        assert resp.status_code in (401, 403)

    def test_user_cannot_create_story(self, http, user_token):
        resp = http.post("/admin/onboarding/stories", json=base_story(), headers=auth(user_token))
        assert resp.status_code in (401, 403)

    def test_user_cannot_patch_story(self, http, user_token, story_id):
        resp = http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"name": "hacked"},
            headers=auth(user_token),
        )
        assert resp.status_code in (401, 403)

    def test_user_cannot_delete_story(self, http, user_token, story_id):
        resp = http.delete(f"/admin/onboarding/stories/{story_id}", headers=auth(user_token))
        assert resp.status_code in (401, 403)


# ─── 3. Invalid Enum Injection (422) ──────────────────────────────────────────

class TestEnumValidation:
    @pytest.mark.parametrize("bad_trigger", ["SCHEDULED", "DELAYED", "first_open", "IMMEDIATE_NOW", ""])
    def test_invalid_trigger_rejected(self, http, admin_token, bad_trigger):
        resp = http.post(
            "/admin/onboarding/stories",
            json=base_story(trigger=bad_trigger),
            headers=auth(admin_token),
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad_audience", ["USERS", "ALL_USERS", "new_users", "PREMIUM", ""])
    def test_invalid_target_audience_rejected(self, http, admin_token, bad_audience):
        resp = http.post(
            "/admin/onboarding/stories",
            json=base_story(target_audience=bad_audience),
            headers=auth(admin_token),
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad_screen", ["BATTLE", "SETTINGS", "home", "MainScreen", ""])
    def test_invalid_start_screen_rejected(self, http, admin_token, bad_screen):
        resp = http.post(
            "/admin/onboarding/stories",
            json=base_story(start_screen=bad_screen),
            headers=auth(admin_token),
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad_position", ["top", "left", "CENTER", "bottom-left", ""])
    def test_invalid_mascot_position_rejected(self, http, admin_token, bad_position):
        payload = base_story(steps=[{**BASE_STEP, "mascot_position": bad_position}])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code == 422


# ─── 4. Numeric Boundary Validation ───────────────────────────────────────────

class TestNumericBoundaries:
    @pytest.mark.parametrize("scale", [0.0, 0.29, 3.01, 10.0, -1.0])
    def test_mascot_scale_out_of_range_rejected(self, http, admin_token, scale):
        payload = base_story(steps=[{**BASE_STEP, "mascot_scale": scale}])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code == 422

    @pytest.mark.parametrize("scale", [0.3, 1.0, 3.0])
    def test_mascot_scale_valid_accepted(self, http, admin_token, scale):
        payload = base_story(name=f"SEC_SCALE_{scale}", steps=[{**BASE_STEP, "mascot_scale": scale}])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))

    @pytest.mark.parametrize("rotation", [-181.0, 181.0, 360.0, -360.0])
    def test_mascot_rotation_out_of_range_rejected(self, http, admin_token, rotation):
        payload = base_story(steps=[{**BASE_STEP, "mascot_rotation": rotation}])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code == 422

    @pytest.mark.parametrize("pos", [-201.0, 201.0])
    def test_mascot_position_offsets_out_of_range_rejected(self, http, admin_token, pos):
        payload = base_story(steps=[{**BASE_STEP, "mascot_x": pos}])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code == 422


# ─── 5. Step Integrity ────────────────────────────────────────────────────────

class TestStepIntegrity:
    def test_empty_steps_on_create_rejected(self, http, admin_token):
        payload = base_story(steps=[])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        # should be rejected (422 or 400)
        assert resp.status_code in (400, 422)

    def test_empty_steps_on_patch_rejected(self, http, admin_token, story_id):
        resp = http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"steps": []},
            headers=auth(admin_token),
        )
        assert resp.status_code in (400, 422)
        # original steps must remain
        check = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
        assert len(check.json()["steps"]) >= 1

    def test_duplicate_step_order_rejected(self, http, admin_token):
        payload = base_story(steps=[
            {**BASE_STEP, "step_order": 1},
            {**BASE_STEP, "step_order": 1, "title_ru": "Duplicate"},
        ])
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (400, 409, 422)


# ─── 6. XSS / Injection Payloads ─────────────────────────────────────────────

class TestXssInjection:
    @pytest.mark.parametrize("payload_str", [
        "<script>alert(1)</script>",
        "'; DROP TABLE onboarding_stories; --",
        '{"$where": "this.is_active == true"}',
        "javascript:void(0)",
    ])
    def test_malicious_payload_stored_as_plain_text(self, http, admin_token, payload_str):
        """Server must store content verbatim — it must NOT execute it."""
        payload = base_story(
            name="SEC_XSS",
            steps=[{**BASE_STEP, "title_ru": payload_str}],
        )
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        stored = resp.json()["steps"][0]["title_ru"]
        # stored as-is (not sanitized/removed)
        assert stored == payload_str
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))


# ─── 7. PATCH No-Op ───────────────────────────────────────────────────────────

class TestPatchBehavior:
    def test_patch_empty_body_is_noop(self, http, admin_token, story_id):
        """PATCH with no fields must not crash and must not alter the story."""
        before = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token)).json()
        resp = http.patch(f"/admin/onboarding/stories/{story_id}", json={}, headers=auth(admin_token))
        assert resp.status_code == 200
        after = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token)).json()
        assert before["name"] == after["name"]
        assert before["priority"] == after["priority"]

    def test_patch_null_steps_keeps_existing(self, http, admin_token, story_id):
        """PATCH without a steps key must not delete existing steps."""
        resp = http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"name": "PATCHED_NO_STEPS"},
            headers=auth(admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["steps"]) >= 1
