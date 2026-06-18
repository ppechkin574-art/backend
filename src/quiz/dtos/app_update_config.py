"""Wire shapes for the admin-controlled app force-update config.

Flat DTOs (no nesting) mapping 1:1 to the `app_update_config` columns:
- `AppUpdateConfigDTO`       — read shape returned to the admin panel.
- `AppUpdateConfigUpdateDTO` — PUT body, all fields optional so the
  admin can patch one platform / one field at a time.

NOTE: the PUBLIC endpoint `GET /app/update-config` keeps its own nested
`{"ios": {...}, "android": {...}}` shape (built by hand in the route) for
backward compatibility with the mobile client — these DTOs are admin-only.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AppUpdateConfigDTO(BaseModel):
    ios_min_build: int
    android_min_build: int
    ios_store_url: str
    android_store_url: str
    # Highest build live in each store (operator-maintained guard).
    ios_last_known_build: int
    android_last_known_build: int
    # Soft-update tier (dismissible prompt below this build).
    ios_recommended_build: int
    android_recommended_build: int

    model_config = {"from_attributes": True}


class AppUpdateConfigUpdateDTO(BaseModel):
    """All optional — admin patches one field at a time."""

    ios_min_build: int | None = Field(default=None, ge=0)
    android_min_build: int | None = Field(default=None, ge=0)
    ios_store_url: str | None = None
    android_store_url: str | None = None
    ios_last_known_build: int | None = Field(default=None, ge=0)
    android_last_known_build: int | None = Field(default=None, ge=0)
    ios_recommended_build: int | None = Field(default=None, ge=0)
    android_recommended_build: int | None = Field(default=None, ge=0)


class AppUpdateConfigAuditDTO(BaseModel):
    """One change-history entry (snapshot before/after a save)."""

    id: int
    changed_at: datetime | None = None
    changed_by: str | None = None
    before_values: dict
    after_values: dict

    model_config = {"from_attributes": True}
