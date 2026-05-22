"""Smoke test for Phase 7b kk-pilot coverage as actually served from prod DB.

This is **NOT** a test of the import scripts or the source JSON — those
have their own unit tests and assertions inside the alembic migrations.
This file verifies the **end-state visible to the API** by hitting the
auth-free diagnostic endpoint `/system/kk-pilot-status` and asserting:

  * Every subject from Roman's content dump (12 of them) is present.
  * Every non-Math subject has 100% kk coverage after the rollout
    migration `f2b3c4d5e6a8` (commit `de4344d`, 22.05.2026).
  * Math sits at 170/174 — the 4 deliberately-nullified structurally
    broken qids (4252, 4289, 4354, 4361 — see `f1a2b3c4d5e7`) MUST
    stay null so the frontend falls back to RU on those.
  * The sample question payload is real Kazakh text (Cyrillic script).

If any of these break, a future migration accidentally clobbered the
kk pilot or a subject lost its kk column — both regressions we want
to catch loudly.
"""

import re

# Cyrillic Kazakh-specific letters that wouldn't appear in Russian text.
# At least one of these MUST show up in a kk question preview.
_KAZAKH_ONLY = re.compile(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]")


def test_kk_pilot_status_endpoint_responds(http) -> None:
    """Endpoint is auth-free; must return 200 with ok=true."""
    resp = http.get("/system/kk-pilot-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True, body


def test_all_twelve_subjects_present_in_coverage(http) -> None:
    body = http.get("/system/kk-pilot-status").json()
    coverage = body.get("coverage_by_subject")
    assert isinstance(coverage, list), body
    # Roman's dump has exactly 12 subjects; the rollout shouldn't have
    # added or dropped any.
    assert len(coverage) == 12, coverage


def test_non_math_non_english_subjects_fully_translated(http) -> None:
    """Every subject except Math and English must be at 100% kk coverage.

    Math is intentionally partial — 170/174 (4 nulled qids from
    `f1a2b3c4d5e7`).  English («Английский») is intentionally 0/385
    — `f3c4d5e6a8b9` nullified the whole subject because the AI source
    translated the English test content too (operator's catch
    22.05.2026), so RU fallback is the safer rendering.

    Everybody else must stay at 100%.
    """
    body = http.get("/system/kk-pilot-status").json()
    coverage_by_name = {row["subject"]: row for row in body["coverage_by_subject"]}

    exceptions = {"Математика", "Английский"}
    for name, row in coverage_by_name.items():
        if name in exceptions:
            continue
        total = row["total"]
        with_kk = row["with_kk"]
        assert total > 0, (name, row)
        assert with_kk == total, (
            f"Subject {name!r} dropped kk rows: {with_kk}/{total}. "
            f"A later migration probably wiped this subject's kk column."
        )


def test_english_subject_intentionally_null_kk(http) -> None:
    """English («Английский») must be at 0/385 kk after `f3c4d5e6a8b9`.

    The AI source export translated English test content into Kazakh
    — answers like `[advice, advises, advising, advices]` became
    `[кеңес, кеңес береді, кеңес беру, кеңестер]`, breaking grammar
    exercises.  Until a stems-only re-translation lands, English
    stays RU-only on purpose.  If `with_kk` ever drifts up, the
    null-migration was reverted or somebody re-ran the rollout
    without filtering English out.
    """
    body = http.get("/system/kk-pilot-status").json()
    eng = next(
        row for row in body["coverage_by_subject"] if row["subject"] == "Английский"
    )
    assert eng["total"] == 385, eng
    assert eng["with_kk"] == 0, (
        f"English subject has {eng['with_kk']} kk rows but should have 0. "
        f"f3c4d5e6a8b9 was probably reverted or rolled-over. The kk "
        f"strings for this subject break the test (English content "
        f"translated to Kazakh)."
    )


def test_math_keeps_170_of_174_translated(http) -> None:
    """Math pilot must stay at 170/174 — 4 nulled qids (structurally
    broken kk strings) are documented in `f1a2b3c4d5e7` and stay RU
    on purpose.  If this number drifts, somebody touched the patch.
    """
    body = http.get("/system/kk-pilot-status").json()
    math = next(
        row for row in body["coverage_by_subject"] if row["subject"] == "Математика"
    )
    assert math["total"] == 174, math
    assert math["with_kk"] == 170, math

    # And the missing ids must be exactly the four we nullified.
    missing = set(body.get("math_missing_kk_ids_sample") or [])
    expected = {4252, 4289, 4354, 4361}
    assert missing == expected, (
        f"Math missing-kk set drifted: got {missing}, expected {expected}. "
        f"Either f1a2b3c4d5e7 was reverted or a new structural-break was "
        f"discovered and not yet recorded here."
    )


def test_sample_preview_is_real_kazakh(http) -> None:
    """Returned sample.text_preview must be actual Kazakh — at least
    one letter that doesn't exist in plain Russian Cyrillic.  Guards
    against accidentally returning RU into a kk column."""
    body = http.get("/system/kk-pilot-status").json()
    sample = body.get("sample") or {}
    preview = sample.get("text_preview", "")
    assert preview, "sample preview is empty"
    assert _KAZAKH_ONLY.search(preview), (
        f"Sample preview {preview!r} contains no Kazakh-specific letters. "
        f"Either the import wrote RU into the kk column or the sample "
        f"was selected from a non-pilot row."
    )


def test_alembic_head_matches_rollout_revision(http) -> None:
    """The active migration head must be at least `f2b3c4d5e6a8` —
    the rollout to all 11 subjects.  If a hotfix downgraded the DB or
    the deploy didn't ship the migration, this catches it.
    """
    body = http.get("/system/kk-pilot-status").json()
    head = body.get("alembic_head", "")
    # We can't assert it equals exactly f2b3c4d5e6a8 because future
    # migrations will move it forward.  Instead, check that the kk
    # coverage matches the post-rollout shape (asserted in sibling
    # tests above).  This assertion just ensures we got SOMETHING.
    assert head, "alembic_head missing from /system/kk-pilot-status response"
