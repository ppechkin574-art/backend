import re
from typing import Annotated

from pydantic import BeforeValidator


def validate_kz_phone(v: str | None) -> str | None:
    if v is None or v == "":
        return v

    pattern = re.compile(r"^\+77\d{9}$")
    if not pattern.match(v):
        raise ValueError("Phone must be a valid Kazakhstan mobile number (+77XXXXXXXXX).")
    return v


KZPhone = Annotated[str | None, BeforeValidator(validate_kz_phone)]


# Allowed display-name characters: Latin, Russian, Kazakh-specific letters,
# digits, space, hyphen. Hyphen lets compound names like "Анна-Мария" through;
# space lets "Иван Петров" through. Everything else (emoji, punctuation, @, +)
# is rejected — that's how phone-numbers and emails leaked into leaderboard
# as display names before this validator existed (Keycloak fallback at
# clients/identity_provider/client.py:531 substituted username/email when
# the name attribute was empty; with this validator name is never empty).
_DISPLAY_NAME_REGEX = re.compile(
    r"^[a-zA-ZА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9 \-]+$"
)

# Lower-cased reserved words people try when prompted for "name". The check
# is case-insensitive and exact-after-trim — partial matches like
# "administrator-pavel" are allowed; we're only blocking literal
# placeholders that look like default values or imply the user is staff.
_RESERVED_DISPLAY_NAMES = frozenset(
    {
        "admin",
        "administrator",
        "админ",
        "администратор",
        "test",
        "тест",
        "user",
        "users",
        "пользователь",
        "пользователи",
        "null",
        "none",
        "undefined",
        "root",
        "support",
        "moderator",
        "модератор",
        "aima",
        "айма",
    }
)


def validate_display_name(v: str) -> str:
    """Normalise and validate a public display name (used in leaderboard,
    profile header, social-style screens).

    Rules:
      - Strip leading/trailing whitespace, collapse runs of inner whitespace
        to a single space. Stops "Иван  Петров" (double space) sneaking
        through and also auto-fixes the trivial trailing-space typo.
      - Length 2..20 AFTER normalisation. Twenty is the operator's chosen
        cap based on Kazakh compound names (e.g. "Нұрсұлтан Назарбаев"
        fits at 19) — going higher invites people pasting essays.
      - Allowed chars: Latin / Russian / Kazakh-specific letters, digits,
        space, hyphen. No emoji, no @, no +, no punctuation. This is the
        line that prevents phone numbers ("+77001234567") and Keycloak
        auto-usernames ("user3") from being accepted as display names.
      - Reject digit-only ("1234" is not a name).
      - Reject lower-cased exact matches against a small reserved-word
        list (admin / test / Пользователь / etc) so the leaderboard
        can't be polluted with placeholder-looking entries either.

    Used by RegistrationCompleteDTO.name. Apply the same rule to any
    future endpoint that accepts a user-visible display name.
    """
    if v is None:
        raise ValueError("Имя обязательно для заполнения.")

    normalised = re.sub(r"\s+", " ", v.strip())

    if len(normalised) < 2:
        raise ValueError("Имя должно содержать минимум 2 символа.")
    if len(normalised) > 20:
        raise ValueError("Имя не должно превышать 20 символов.")

    if not _DISPLAY_NAME_REGEX.match(normalised):
        raise ValueError(
            "Имя может содержать только буквы (русские, казахские, английские),"
            " цифры, пробел и дефис."
        )

    if normalised.replace(" ", "").replace("-", "").isdigit():
        raise ValueError("Имя не может состоять только из цифр.")

    if normalised.lower() in _RESERVED_DISPLAY_NAMES:
        raise ValueError("Это имя зарезервировано. Выберите другое.")

    return normalised


DisplayName = Annotated[str, BeforeValidator(validate_display_name)]
