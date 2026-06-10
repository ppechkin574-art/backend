"""Wire shapes for the admin-controlled app force-update config.

Flat DTOs (no nesting) mapping 1:1 to the `app_update_config` columns:
- `AppUpdateConfigDTO`       — read shape returned to the admin panel.
- `AppUpdateConfigUpdateDTO` — PUT body, all fields optional so the
  admin can patch one platform / one field at a time.

NOTE: the PUBLIC endpoint `GET /app/update-config` keeps its own nested
`{"ios": {...}, "android": {...}}` shape (built by hand in the route) for
backward compatibility with the mobile client — these DTOs are admin-only.
"""

from pydantic import BaseModel, Field


class AppUpdateConfigDTO(BaseModel):
    ios_min_build: int
    android_min_build: int
    ios_store_url: str
    android_store_url: str

    model_config = {"from_attributes": True}


class AppUpdateConfigUpdateDTO(BaseModel):
    """All optional — admin patches one field at a time."""

    ios_min_build: int | None = Field(default=None, ge=0)
    android_min_build: int | None = Field(default=None, ge=0)
    ios_store_url: str | None = None
    android_store_url: str | None = None
