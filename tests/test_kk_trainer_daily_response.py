"""Smoke tests: Kazakh text served from trainer and daily-test endpoints.

Exercises the full HTTP path that the Flutter client walks:
  login → POST /user/trainers/attempts/create   (Accept-Language: kk / ru)
  login → GET  /user/daily-tests/today          (Accept-Language: kk / ru)

Contract:
  - locale=kk → at least one block contains a Kazakh-specific letter
    (ә / і / ң / ғ / ү / ұ / қ / ө / һ) — means _splice_kk_translations ran.
  - locale=ru → Kazakh-heavy responses are forbidden (ratio < 10 %).

Math trainer is targeted because Math is the only subject whose original
DB content is Russian and needs the splice to produce KK.  Other subjects
already store KK in question_blocks and are returned correctly even without
the header, so testing them doesn't reveal splice regressions.

The test mobile account (+77001234567 / Test12345!) must have an active
subscription; otherwise the route returns 402/403 and the test is skipped
with an explanatory message.
"""

import re
import time

import pytest

from tests.conftest import wait_for_rate_limit_reset

_KAZAKH_ONLY = re.compile(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]")

# Математика subject_id is 1 in both prod and staging.
_MATH_SUBJECT_ID = 1


def _login(http, mobile_credentials) -> str:
    login, password = mobile_credentials
    time.sleep(13)
    resp = http.post("/auth/login", json={"login": login, "password": password})
    if resp.status_code == 429:
        wait_for_rate_limit_reset()
        resp = http.post("/auth/login", json={"login": login, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _pick_math_trainer_id(http, token: str) -> int:
    resp = http.get(
        f"/user/trainers/subjects/{_MATH_SUBJECT_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    body = resp.json()
    topics = body.get("data") or []
    assert topics, f"No topics for subject {_MATH_SUBJECT_ID}: {body}"
    trainers = topics[0].get("trainers") or []
    assert trainers, f"No trainers in first Math topic: {topics[0]}"
    return trainers[0]["id"]


def _create_trainer_attempt(http, token: str, trainer_id: int, locale: str) -> dict:
    resp = http.post(
        "/user/trainers/attempts/create",
        json={"topic_id": None, "trainer_id": trainer_id},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept-Language": locale,
        },
    )
    if resp.status_code in (402, 403):
        pytest.skip(
            f"Trainer attempt returned {resp.status_code} — test mobile account "
            f"has no active subscription. Grant PRO and re-run."
        )
    resp.raise_for_status()
    return resp.json()


def _get_today_daily_test(http, token: str, locale: str) -> dict:
    resp = http.get(
        "/user/daily-tests/today",
        params={"subject_id": _MATH_SUBJECT_ID},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept-Language": locale,
        },
    )
    if resp.status_code in (402, 403):
        pytest.skip(
            f"Daily test returned {resp.status_code} — test mobile account "
            f"has no active subscription. Grant PRO and re-run."
        )
    resp.raise_for_status()
    return resp.json()


def _block_values(attempt_payload: dict) -> list[str]:
    out: list[str] = []
    for q in attempt_payload.get("questions") or []:
        for b in q.get("blocks") or []:
            if b.get("value"):
                out.append(b["value"])
        for v in q.get("variants") or []:
            for b in v.get("blocks") or []:
                if b.get("value"):
                    out.append(b["value"])
    return out


# ──────────────────────── trainer tests ────────────────────────────


def test_trainer_kk_locale_returns_kazakh_math_blocks(http, mobile_credentials):
    """Math trainer with Accept-Language: kk must contain Kazakh-specific letters."""
    token = _login(http, mobile_credentials)
    trainer_id = _pick_math_trainer_id(http, token)
    attempt = _create_trainer_attempt(http, token, trainer_id, "kk")

    blocks = _block_values(attempt)
    assert blocks, "Trainer attempt returned no blocks — route shape may have changed."

    kk_hits = [v for v in blocks if _KAZAKH_ONLY.search(v)]
    assert kk_hits, (
        f"Trainer (locale=kk) returned {len(blocks)} blocks but none "
        f"contained Kazakh-specific characters. _splice_kk_translations "
        f"may not have run, or question_text_kk is NULL for all Math "
        f"questions. Trainer ID={trainer_id}."
    )


def test_trainer_ru_locale_does_not_return_kk_heavy_math_blocks(http, mobile_credentials):
    """Math trainer with Accept-Language: ru must NOT be dominated by Kazakh text."""
    token = _login(http, mobile_credentials)
    trainer_id = _pick_math_trainer_id(http, token)
    attempt = _create_trainer_attempt(http, token, trainer_id, "ru")

    blocks = _block_values(attempt)
    assert blocks

    kk_hits = [v for v in blocks if _KAZAKH_ONLY.search(v)]
    ratio = len(kk_hits) / len(blocks)
    assert ratio < 0.10, (
        f"Trainer (locale=ru) returned {ratio:.0%} Kazakh blocks — "
        f"splice should be inactive for RU locale."
    )


# ──────────────────────── daily-test tests ─────────────────────────


def test_daily_test_kk_locale_returns_kazakh_math_blocks(http, mobile_credentials):
    """Daily test (Math, locale=kk) must contain Kazakh-specific letters."""
    token = _login(http, mobile_credentials)
    attempt = _get_today_daily_test(http, token, "kk")

    blocks = _block_values(attempt)
    assert blocks, "Daily test returned no blocks — route shape may have changed."

    kk_hits = [v for v in blocks if _KAZAKH_ONLY.search(v)]
    assert kk_hits, (
        f"Daily test (locale=kk) returned {len(blocks)} blocks but none "
        f"contained Kazakh-specific characters. _splice_kk_translations "
        f"may not have run for daily_tests service."
    )


def test_daily_test_ru_locale_does_not_return_kk_heavy_blocks(http, mobile_credentials):
    """Daily test (Math, locale=ru) must NOT be dominated by Kazakh text."""
    token = _login(http, mobile_credentials)
    attempt = _get_today_daily_test(http, token, "ru")

    blocks = _block_values(attempt)
    assert blocks

    kk_hits = [v for v in blocks if _KAZAKH_ONLY.search(v)]
    ratio = len(kk_hits) / len(blocks)
    assert ratio < 0.10, (
        f"Daily test (locale=ru) returned {ratio:.0%} Kazakh blocks — "
        f"splice should be inactive for RU locale."
    )
