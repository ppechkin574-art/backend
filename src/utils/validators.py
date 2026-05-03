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
