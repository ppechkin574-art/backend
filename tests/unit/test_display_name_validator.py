"""DisplayName validator — the server-side guard that stops phone
numbers, emails and reserved words from being saved as a user's
public display name.

Background (18.05.2026): three legacy accounts (`dnns`, `+77001234567`,
`user3`) shipped to production with no name attribute filled, and
the Keycloak client at clients/identity_provider/client.py:531 silently
substituted username/email — so the leaderboard rendered raw phone
numbers and auto-usernames as if they were real names. The
RegistrationCompleteDTO now uses DisplayName which rejects all three
patterns up-front; this test pins the contract so the validator
doesn't drift later (e.g. someone broadens the regex to allow `@`
because they want emails and accidentally re-opens the leak).
"""

import pytest
from pydantic import BaseModel, ValidationError

from utils.validators import DisplayName, validate_display_name


class _Model(BaseModel):
    """Tiny wrapper so we exercise validate_display_name the same way
    a real DTO does (through pydantic's annotated BeforeValidator)
    rather than calling the function directly. Catches integration
    issues like annotation-vs-function divergence."""

    name: DisplayName


# ───────────────────────── happy path ─────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Иван",
        "Айдар",
        "Нұрсұлтан",
        "John",
        "Анна-Мария",
        "Mike2024",
        "Лука Б",
        "Pavel P",
        "Әсемгүл",
        "Қайрат",
    ],
)
def test_accepts_realistic_names(name):
    assert _Model(name=name).name == name


def test_trims_leading_and_trailing_whitespace():
    """Real users hit the spacebar by accident — auto-fix instead of
    nagging them with a validation error."""
    assert _Model(name="  Иван  ").name == "Иван"


def test_collapses_inner_whitespace():
    """Two spaces between first and last name should become one."""
    assert _Model(name="Иван   Петров").name == "Иван Петров"


def test_allows_minimum_two_chars():
    assert _Model(name="Ян").name == "Ян"


def test_allows_maximum_twenty_chars():
    twenty_char = "А" * 20
    assert _Model(name=twenty_char).name == twenty_char


# ───────────────────────── PII / leak protection ─────────────────────────


@pytest.mark.parametrize(
    "phone_like",
    [
        "+77001234567",
        "77001234567",
        "+7 700 123 4567",
        "+1-555-1234",
    ],
)
def test_rejects_phone_numbers(phone_like):
    """The original 18.05.2026 bug: phone leaked as display name via
    the Keycloak fallback. The validator must refuse to even accept
    such a payload at registration time so it never reaches the
    leaderboard."""
    with pytest.raises(ValidationError):
        _Model(name=phone_like)


@pytest.mark.parametrize(
    "email_like",
    [
        "user@example.com",
        "test@aima.kz",
        "иван@домен.рф",
    ],
)
def test_rejects_emails(email_like):
    with pytest.raises(ValidationError):
        _Model(name=email_like)


@pytest.mark.parametrize(
    "garbage",
    [
        "user@",
        "@admin",
        "Иван!",
        "🔥top🔥",
        "Иван.Петров",
        "user/admin",
    ],
)
def test_rejects_disallowed_characters(garbage):
    with pytest.raises(ValidationError):
        _Model(name=garbage)


# ───────────────────────── reserved words ─────────────────────────


@pytest.mark.parametrize(
    "reserved",
    [
        "admin",
        "Admin",
        "ADMIN",
        "администратор",
        "Администратор",
        "test",
        "ТЕСТ",
        "user",
        "пользователь",
        "Пользователь",
        "null",
        "none",
        "root",
        "support",
        "aima",
        "АЙМА",
    ],
)
def test_rejects_reserved_words(reserved):
    """Case-insensitive exact match — staff-implying or placeholder-
    looking names are off-limits. Partial matches like
    'administrator-pavel' should still pass (test below)."""
    with pytest.raises(ValidationError):
        _Model(name=reserved)


def test_allows_compound_name_containing_reserved_substring():
    """The reserved check is on the whole normalised string, not a
    substring search — otherwise legitimate names like
    'administrator-pavel' (or just 'Pavel-Admin') get false-rejected."""
    # 'admin-pavel' is 11 chars, within length cap
    assert _Model(name="admin-pavel").name == "admin-pavel"


# ───────────────────────── length / blankness ─────────────────────────


@pytest.mark.parametrize("too_short", ["", " ", "  ", "А", "  А  "])
def test_rejects_too_short(too_short):
    """After trim+collapse, must be >= 2 chars."""
    with pytest.raises(ValidationError):
        _Model(name=too_short)


def test_rejects_too_long():
    twenty_one = "А" * 21
    with pytest.raises(ValidationError):
        _Model(name=twenty_one)


def test_rejects_digits_only():
    """`1234` is not a name even though it satisfies the character
    class — explicit digit-only block protects against people
    just typing a year or a random number."""
    with pytest.raises(ValidationError):
        _Model(name="1234")


def test_rejects_none_direct():
    """Direct call (outside pydantic) raises ValueError. Inside a
    DTO pydantic wraps it into ValidationError — both paths reject."""
    with pytest.raises(ValueError):
        validate_display_name(None)  # type: ignore[arg-type]


# ───────────────────────── happy path: edge-case kazakh chars ─────────────


@pytest.mark.parametrize(
    "kazakh_char_name",
    [
        "Әсет",  # Ә
        "Іңкәр",  # І, ң, ә
        "Ғазиз",  # Ғ
        "Ұлжан",  # Ұ
        "Үмбет",  # Ү
        "Қанат",  # Қ
        "Өтеген",  # Ө
        "Һадиша",  # Һ
    ],
)
def test_accepts_kazakh_specific_letters(kazakh_char_name):
    """The regex character class must cover all 9 Kazakh-specific
    letters (both cases). Easy to forget one of them and silently
    block legitimate users — this test fails loudly if anyone
    trims the class."""
    assert _Model(name=kazakh_char_name).name == kazakh_char_name
