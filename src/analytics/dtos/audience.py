from pydantic import BaseModel, ConfigDict


class AudienceCountDTO(BaseModel):
    """A single (name, count) bucket. Counts only — no PII."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    count: int


class AudienceDTO(BaseModel):
    """Marketing-safe audience aggregate over ALL Keycloak users.

    Counts only — never user lists / emails / phones. Safe for the
    `marketing` role. Built backend-side by paginating the whole
    Keycloak directory and bucketing by the per-user `role` / `plan` /
    `grade` attributes; cached in Redis because the full fetch is heavy.
    """

    model_config = ConfigDict(from_attributes=True)

    total: int = 0
    by_role: list[AudienceCountDTO] = []
    by_plan: list[AudienceCountDTO] = []
    by_grade: list[AudienceCountDTO] = []
