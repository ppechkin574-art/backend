"""Accept-Language → request.state.locale resolution (Phase 7b).

Tests the pure `resolve_locale` helper directly so we don't need to
spin up the full ASGI stack — keeps the test cheap and decoupled from
auth/DB/redis dependencies that the rest of the unit suite also avoids.
"""

import pytest

from api.middlewares.locale import resolve_locale


@pytest.mark.parametrize(
    "header,expected",
    [
        # ── kk variants ──
        ("kk", "kk"),
        ("KK", "kk"),
        ("kk-KZ", "kk"),
        ("kk-Cyrl-KZ", "kk"),
        ("kk;q=0.9", "kk"),
        ("kk-KZ,ru;q=0.5", "kk"),
        # ── ru variants ──
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("ru-RU,en;q=0.8", "ru"),
        # ── defaults ──
        (None, "ru"),
        ("", "ru"),
        ("   ", "ru"),
        # ── unsupported tag → defensive default ──
        ("en", "ru"),
        ("en-US,fr;q=0.8", "ru"),
        ("garbage-tag-here", "ru"),
    ],
)
def test_resolve_locale(header: str | None, expected: str) -> None:
    assert resolve_locale(header) == expected


def test_resolve_locale_strips_whitespace() -> None:
    assert resolve_locale("  kk  ") == "kk"


def test_resolve_locale_first_tag_wins() -> None:
    """RFC 5646 — quality values are NOT parsed in the pilot.  Whatever
    comes first wins.  This mirrors the doc-string of the helper and
    guards against someone silently adding q-value handling without
    updating the contract."""
    assert resolve_locale("kk,ru") == "kk"
    assert resolve_locale("ru,kk") == "ru"
