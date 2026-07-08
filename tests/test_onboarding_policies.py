"""
Onboarding policy coverage — all 9 API paths, all display-policy fields.

Endpoints covered:
  ADMIN
    GET  /admin/onboarding/stories
    POST /admin/onboarding/stories
    GET  /admin/onboarding/stories/{id}
    PATCH /admin/onboarding/stories/{id}
    DELETE /admin/onboarding/stories/{id}
  USER (mobile)
    GET  /onboarding/stories
    GET  /onboarding/stories/views
    POST /onboarding/stories/{id}/view

Policy fields verified:
  is_active, is_test, priority, trigger, immediate_count,
  max_shows_per_user, target_audience, new_user_days,
  skip_delay_seconds, is_mandatory, start_screen
"""

import time

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────

def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


BASE_STEP = {
    "step_order": 1,
    "mascot_image_url": None,
    "title_ru": "Тест",
    "title_kk": "Тест KK",
    "body_ru": "Тело RU",
    "body_kk": "Тело KK",
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
        "name": "POLICY_TEST",
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
        "steps": [BASE_STEP],
    }
    s.update(overrides)
    return s


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def user_token(http, mobile_credentials):
    """Mobile-user JWT — obtained once per session."""
    login, pw = mobile_credentials
    resp = http.post("/auth/login", json={"login": login, "password": pw})
    if resp.status_code == 429:
        time.sleep(65)
        resp = http.post("/auth/login", json={"login": login, "password": pw})
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def story_id(http, admin_token):
    """Creates a base test story; deletes it after the module."""
    resp = http.post(
        "/admin/onboarding/stories",
        json=base_story(),
        headers=auth(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    sid = resp.json()["id"]
    yield sid
    http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 1. API Path Coverage — Admin ─────────────────────────────────────────────

class TestAdminPaths:
    def test_list_all(self, http, admin_token):
        resp = http.get("/admin/onboarding/stories", headers=auth(admin_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_one(self, http, admin_token, story_id):
        resp = http.get(f"/admin/onboarding/stories/{story_id}", headers=auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["id"] == story_id

    def test_get_nonexistent_404(self, http, admin_token):
        resp = http.get("/admin/onboarding/stories/999999999", headers=auth(admin_token))
        assert resp.status_code == 404

    def test_create_returns_201(self, http, admin_token):
        payload = base_story(name="POLICY_TEMP_CREATE")
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        new_id = resp.json()["id"]
        # cleanup
        http.delete(f"/admin/onboarding/stories/{new_id}", headers=auth(admin_token))

    def test_patch_name(self, http, admin_token, story_id):
        resp = http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"name": "POLICY_TEST_RENAMED"},
            headers=auth(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "POLICY_TEST_RENAMED"
        # restore
        http.patch(
            f"/admin/onboarding/stories/{story_id}",
            json={"name": "POLICY_TEST"},
            headers=auth(admin_token),
        )

    def test_delete_removes_story(self, http, admin_token):
        resp = http.post(
            "/admin/onboarding/stories",
            json=base_story(name="POLICY_TO_DELETE"),
            headers=auth(admin_token),
        )
        assert resp.status_code in (200, 201)
        new_id = resp.json()["id"]

        del_resp = http.delete(f"/admin/onboarding/stories/{new_id}", headers=auth(admin_token))
        assert del_resp.status_code == 204

        get_resp = http.get(f"/admin/onboarding/stories/{new_id}", headers=auth(admin_token))
        assert get_resp.status_code == 404

    def test_delete_cascades_steps(self, http, admin_token):
        """Steps should be removed with the story (cascade delete)."""
        payload = base_story(
            name="POLICY_CASCADE",
            steps=[
                {**BASE_STEP, "step_order": 1},
                {**BASE_STEP, "step_order": 2, "title_ru": "Step 2"},
            ],
        )
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        new_id = resp.json()["id"]
        assert len(resp.json()["steps"]) == 2

        http.delete(f"/admin/onboarding/stories/{new_id}", headers=auth(admin_token))
        # story gone — if steps leaked, the DB FK would prevent this from being 404
        assert http.get(f"/admin/onboarding/stories/{new_id}", headers=auth(admin_token)).status_code == 404


# ─── 2. API Path Coverage — User (mobile) ─────────────────────────────────────

class TestUserPaths:
    def test_list_active_stories(self, http, user_token):
        resp = http.get("/onboarding/stories", headers=auth(user_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_views(self, http, user_token):
        resp = http.get("/onboarding/stories/views", headers=auth(user_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_record_view_completed(self, http, admin_token, user_token):
        # activate story so it's accessible
        payload = base_story(name="POLICY_VIEW_TEST", is_active=True, is_test=False)
        create = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert create.status_code in (200, 201)
        sid = create.json()["id"]

        resp = http.post(
            f"/onboarding/stories/{sid}/view",
            json={"story_id": sid, "skipped": False},
            headers=auth(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["story_id"] == sid
        assert body["view_count"] == 1
        assert body["completed_at"] is not None
        assert body["skipped_at"] is None

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    def test_record_view_skipped(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_SKIP_TEST", is_active=True, is_test=False)
        create = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        sid = create.json()["id"]

        resp = http.post(
            f"/onboarding/stories/{sid}/view",
            json={"story_id": sid, "skipped": True},
            headers=auth(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped_at"] is not None
        assert body["completed_at"] is None

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    def test_record_view_nonexistent_story(self, http, user_token):
        resp = http.post(
            "/onboarding/stories/999999999/view",
            json={"story_id": 999999999, "skipped": False},
            headers=auth(user_token),
        )
        assert resp.status_code == 404

    def test_path_story_id_wins_over_body(self, http, admin_token, user_token):
        """URL path story_id must override body.story_id — backend sets body.story_id = path."""
        payload = base_story(name="POLICY_PATHWIN", is_active=True, is_test=False)
        create = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        real_id = create.json()["id"]

        # path = real_id, body = 999999999 (non-existent)
        resp = http.post(
            f"/onboarding/stories/{real_id}/view",
            json={"story_id": 999999999, "skipped": False},
            headers=auth(user_token),
        )
        # should succeed for real_id (path wins)
        assert resp.status_code == 200
        assert resp.json()["story_id"] == real_id

        http.delete(f"/admin/onboarding/stories/{real_id}", headers=auth(admin_token))


# ─── 3. is_active Policy ──────────────────────────────────────────────────────

class TestIsActivePolicy:
    def test_inactive_story_not_in_public_list(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_INACTIVE", is_active=False, is_test=False)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        sid = resp.json()["id"]

        public = http.get("/onboarding/stories", headers=auth(user_token)).json()
        ids = [s["id"] for s in public]
        assert sid not in ids

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    def test_active_story_in_public_list(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_ACTIVE", is_active=True, is_test=False)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        sid = resp.json()["id"]

        public = http.get("/onboarding/stories", headers=auth(user_token)).json()
        ids = [s["id"] for s in public]
        assert sid in ids

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    def test_toggle_active_appears_disappears(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_TOGGLE", is_active=False, is_test=False)
        sid = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token)).json()["id"]

        # Activate
        http.patch(f"/admin/onboarding/stories/{sid}", json={"is_active": True}, headers=auth(admin_token))
        public_ids = [s["id"] for s in http.get("/onboarding/stories", headers=auth(user_token)).json()]
        assert sid in public_ids

        # Deactivate
        http.patch(f"/admin/onboarding/stories/{sid}", json={"is_active": False}, headers=auth(admin_token))
        public_ids = [s["id"] for s in http.get("/onboarding/stories", headers=auth(user_token)).json()]
        assert sid not in public_ids

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 4. is_test Policy ────────────────────────────────────────────────────────

class TestIsTestPolicy:
    def test_test_story_hidden_from_non_test_phone(self, http, admin_token, user_token):
        """Mobile test user (+77001234567) is NOT in ONBOARDING_TEST_PHONES."""
        payload = base_story(name="POLICY_IS_TEST", is_active=True, is_test=True)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        sid = resp.json()["id"]

        public = http.get("/onboarding/stories", headers=auth(user_token)).json()
        assert sid not in [s["id"] for s in public]

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 5. Priority Ordering ─────────────────────────────────────────────────────

class TestPriorityOrdering:
    def test_higher_priority_first(self, http, admin_token, user_token):
        lo = http.post(
            "/admin/onboarding/stories",
            json=base_story(name="POLICY_PRIO_LOW", priority=1, is_active=True, is_test=False),
            headers=auth(admin_token),
        ).json()["id"]

        hi = http.post(
            "/admin/onboarding/stories",
            json=base_story(name="POLICY_PRIO_HIGH", priority=100, is_active=True, is_test=False),
            headers=auth(admin_token),
        ).json()["id"]

        public = http.get("/onboarding/stories", headers=auth(user_token)).json()
        ids = [s["id"] for s in public]
        assert ids.index(hi) < ids.index(lo)

        http.delete(f"/admin/onboarding/stories/{hi}", headers=auth(admin_token))
        http.delete(f"/admin/onboarding/stories/{lo}", headers=auth(admin_token))


# ─── 6. View Count Tracking ───────────────────────────────────────────────────

class TestViewCountTracking:
    def test_view_count_increments(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_VIEWCOUNT", is_active=True, is_test=False, max_shows_per_user=5)
        sid = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token)).json()["id"]

        for expected in (1, 2, 3):
            resp = http.post(
                f"/onboarding/stories/{sid}/view",
                json={"story_id": sid, "skipped": False},
                headers=auth(user_token),
            )
            assert resp.status_code == 200
            assert resp.json()["view_count"] == expected

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))

    def test_views_endpoint_reflects_count(self, http, admin_token, user_token):
        payload = base_story(name="POLICY_VIEWS_ENDPOINT", is_active=True, is_test=False)
        sid = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token)).json()["id"]

        http.post(
            f"/onboarding/stories/{sid}/view",
            json={"story_id": sid, "skipped": False},
            headers=auth(user_token),
        )

        views = http.get("/onboarding/stories/views", headers=auth(user_token)).json()
        assert str(sid) in views or sid in views

        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 7. Trigger + Immediate Count Round-Trip ──────────────────────────────────

class TestTriggerField:
    @pytest.mark.parametrize("trigger", ["FIRST_OPEN", "IMMEDIATE"])
    def test_trigger_stored_and_returned(self, http, admin_token, trigger):
        payload = base_story(name=f"POLICY_TRIGGER_{trigger}", trigger=trigger, immediate_count=3)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["trigger"] == trigger
        assert body["immediate_count"] == 3
        http.delete(f"/admin/onboarding/stories/{body['id']}", headers=auth(admin_token))

    def test_public_dto_includes_trigger(self, http, admin_token, user_token):
        payload = base_story(
            name="POLICY_TRIGGER_PUBLIC", is_active=True, is_test=False,
            trigger="IMMEDIATE", immediate_count=2,
        )
        sid = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token)).json()["id"]
        public = http.get("/onboarding/stories", headers=auth(user_token)).json()
        story = next((s for s in public if s["id"] == sid), None)
        assert story is not None
        assert story["trigger"] == "IMMEDIATE"
        assert story["immediate_count"] == 2
        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 8. All Policy Fields Round-Trip ──────────────────────────────────────────

class TestPolicyFieldRoundTrip:
    @pytest.mark.parametrize("start_screen", ["HOME", "TRAINER", "PROFILE", "LEADERBOARD", "SUBSCRIPTION"])
    def test_start_screen_values(self, http, admin_token, start_screen):
        payload = base_story(name=f"POLICY_SS_{start_screen}", start_screen=start_screen)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        assert resp.json()["start_screen"] == start_screen
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))

    @pytest.mark.parametrize("audience", ["ALL", "NEW_USERS"])
    def test_target_audience_values(self, http, admin_token, audience):
        payload = base_story(name=f"POLICY_TA_{audience}", target_audience=audience, new_user_days=14)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["target_audience"] == audience
        assert data["new_user_days"] == 14
        http.delete(f"/admin/onboarding/stories/{data['id']}", headers=auth(admin_token))

    def test_mandatory_and_skip_delay(self, http, admin_token):
        payload = base_story(name="POLICY_MANDATORY", is_mandatory=True, skip_delay_seconds=10)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["is_mandatory"] is True
        assert data["skip_delay_seconds"] == 10
        http.delete(f"/admin/onboarding/stories/{data['id']}", headers=auth(admin_token))

    def test_max_shows_per_user_stored(self, http, admin_token):
        payload = base_story(name="POLICY_MAX_SHOWS", max_shows_per_user=5)
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.json()["max_shows_per_user"] == 5
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))


# ─── 9. Steps Ordering ────────────────────────────────────────────────────────

class TestStepsOrdering:
    def test_steps_sorted_by_step_order(self, http, admin_token):
        payload = base_story(
            name="POLICY_STEP_ORDER",
            steps=[
                {**BASE_STEP, "step_order": 3, "title_ru": "Third"},
                {**BASE_STEP, "step_order": 1, "title_ru": "First"},
                {**BASE_STEP, "step_order": 2, "title_ru": "Second"},
            ],
        )
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        steps = resp.json()["steps"]
        orders = [s["step_order"] for s in steps]
        assert orders == sorted(orders)
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))

    def test_patch_replaces_steps_atomically(self, http, admin_token):
        payload = base_story(name="POLICY_PATCH_STEPS", steps=[{**BASE_STEP, "step_order": 1}])
        sid = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token)).json()["id"]

        new_steps = [
            {**BASE_STEP, "step_order": 1, "title_ru": "New 1"},
            {**BASE_STEP, "step_order": 2, "title_ru": "New 2"},
        ]
        resp = http.patch(
            f"/admin/onboarding/stories/{sid}",
            json={"steps": new_steps},
            headers=auth(admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["steps"]) == 2
        assert resp.json()["steps"][0]["title_ru"] == "New 1"
        http.delete(f"/admin/onboarding/stories/{sid}", headers=auth(admin_token))


# ─── 10. Unicode in Text Fields ───────────────────────────────────────────────

class TestUnicodeRoundTrip:
    def test_kazakh_chars_in_title(self, http, admin_token):
        kk_title = "Қазақша тест: Ғ Ү Ұ Ң Ө Ә"
        payload = base_story(
            name="POLICY_UNICODE",
            steps=[{**BASE_STEP, "title_kk": kk_title}],
        )
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["steps"][0]["title_kk"] == kk_title
        http.delete(f"/admin/onboarding/stories/{data['id']}", headers=auth(admin_token))

    def test_cyrillic_and_emoji_in_body(self, http, admin_token):
        body = "Тест 🎓 Подготовка к ЕНТ — успех!"
        payload = base_story(
            name="POLICY_EMOJI",
            steps=[{**BASE_STEP, "body_ru": body}],
        )
        resp = http.post("/admin/onboarding/stories", json=payload, headers=auth(admin_token))
        assert resp.status_code in (200, 201)
        assert resp.json()["steps"][0]["body_ru"] == body
        http.delete(f"/admin/onboarding/stories/{resp.json()['id']}", headers=auth(admin_token))
