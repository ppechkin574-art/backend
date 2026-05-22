"""End-to-end smoke for the actual Kazakh text returned to the client.

Operator's complaint 22.05.2026: "тесты именно того текста который
по факту отдаётся пользователю, а не тот который ты импортируешь".
Unit tests on the splice helper cover the transformation rule; this
file exercises the live HTTP path the mobile client actually walks:

  1.  POST /auth/login                            → access token
  2.  GET  /user/ents/subject-combinations        → discover a valid id
  3.  POST /user/ents/attempts/create-full-exam   with Accept-Language: kk
  4.  Inspect response.questions[...] block values for actual Kazakh
      script — at least one block must contain `ң` / `ғ` / `қ` / `ұ` /
      `ө` / `һ` / `ә` / `і`, which appear in Kazakh but not in plain
      Russian Cyrillic.

If the test mobile account doesn't have an active subscription the
ENT-attempt routes refuse with 4xx — the test skips with a clear
message so it doesn't pollute CI red for an env-setup issue.

The same flow with Accept-Language: ru is exercised as a fallback
contract test — the splice must NOT swap in kk for the RU client.
"""

import re
import time

import pytest

from tests.conftest import wait_for_rate_limit_reset

_KAZAKH_ONLY = re.compile(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]")


def _login(http, mobile_credentials) -> str:
    login, password = mobile_credentials
    # Stagger to dodge cross-test rate-limit collisions.
    time.sleep(13)
    resp = http.post("/auth/login", json={"login": login, "password": password})
    if resp.status_code == 429:
        wait_for_rate_limit_reset()
        resp = http.post("/auth/login", json={"login": login, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _pick_subject_combination_id(http, token: str) -> int:
    resp = http.get(
        "/user/ents/subject-combinations",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    body = resp.json()
    assert isinstance(body, list) and body, body
    # First combination is fine — pilot covers all Math subjects either
    # way, and we only need ONE kk question to assert.
    return body[0]["id"]


def _create_full_exam(
    http, token: str, locale: str, subj_comb_id: int
) -> dict:
    resp = http.post(
        "/user/ents/attempts/create-full-exam",
        json={"subject_combination_id": subj_comb_id},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept-Language": locale,
        },
    )
    if resp.status_code in (402, 403):
        pytest.skip(
            f"create-full-exam returned {resp.status_code} — test mobile "
            f"account has no active subscription. Grant trial/seed PRO "
            f"and re-run."
        )
    resp.raise_for_status()
    return resp.json()


def _flatten_block_values(attempt_payload: dict) -> list[str]:
    """Walk both `flat` (by_subject) and `grouped` (full_exam) shapes
    and return every block's `value` (including variants).
    """
    out: list[str] = []
    qs = attempt_payload.get("questions") or []
    if not qs:
        return out
    if isinstance(qs[0], dict) and "questions" in qs[0]:
        # Grouped by subject — full_exam shape.
        nested = [q for grp in qs for q in (grp.get("questions") or [])]
    else:
        nested = qs
    for q in nested:
        for b in q.get("blocks") or []:
            v = b.get("value")
            if v:
                out.append(v)
        for var in q.get("variants") or []:
            for b in var.get("blocks") or []:
                v = b.get("value")
                if v:
                    out.append(v)
    return out


def test_create_full_exam_returns_kazakh_when_locale_kk(
    http, mobile_credentials
) -> None:
    """With `Accept-Language: kk`, the questions+variants returned by
    create-full-exam must contain actual Kazakh script.  Stronger than
    the coverage test in `test_kk_pilot_coverage.py` because it
    exercises the full splice path: header → middleware → service.
    """
    token = _login(http, mobile_credentials)
    subj_comb_id = _pick_subject_combination_id(http, token)
    attempt = _create_full_exam(http, token, "kk", subj_comb_id)

    block_values = _flatten_block_values(attempt)
    assert block_values, (
        "Attempt returned without question/variant blocks at all — "
        "either the route changed shape or pilot subjects are empty."
    )

    kk_hits = [v for v in block_values if _KAZAKH_ONLY.search(v)]
    assert kk_hits, (
        f"Not a single block in the {len(block_values)}-block response "
        f"contained Kazakh-specific letters. The splice or the data "
        f"migration regressed — check /system/kk-pilot-status for "
        f"coverage and Railway logs for the locale value the route "
        f"received."
    )


def test_create_full_exam_returns_russian_when_locale_ru(
    http, mobile_credentials
) -> None:
    """RU fallback contract — `Accept-Language: ru` must NOT inject
    Kazakh into the response.  Guards against an accidental "always
    return kk" regression on the locale resolver.
    """
    token = _login(http, mobile_credentials)
    subj_comb_id = _pick_subject_combination_id(http, token)
    attempt = _create_full_exam(http, token, "ru", subj_comb_id)

    block_values = _flatten_block_values(attempt)
    assert block_values
    kk_hits = [v for v in block_values if _KAZAKH_ONLY.search(v)]
    # NOTE: question texts of Kazakh History (subject "История Казахстана")
    # may include Kazakh proper nouns in their RU original (e.g.
    # "Әбілқайыр хан"), so 0 isn't enforceable.  We assert that the
    # MAJORITY of blocks are plain Russian — Kazakh-ratio must be small.
    ratio = len(kk_hits) / len(block_values)
    assert ratio < 0.10, (
        f"Locale=ru returned a kk-heavy response ({ratio:.0%} of "
        f"blocks contain Kazakh-specific letters). The middleware "
        f"probably ignored the header and defaulted to kk."
    )
