from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# "interval"      — reset every `interval_days` days after the last reset.
# "weekly_monday" — reset every Monday 00:00 Asia/Almaty (CRM task #6,
#                    "Еженедельный спринт").
ResetMode = Literal["interval", "weekly_monday"]


class LeaderboardPointsSettingsDTO(BaseModel):
    auto_reset_enabled: bool
    reset_mode: ResetMode
    interval_days: int
    last_reset_at: datetime | None = None
    next_reset_at: datetime | None = None
    # CRM task #7 ("Еженедельный спринт"): points threshold that locks
    # in the week's sprint winner. None/0 == feature off.
    sprint_target_points: int | None = None
    # CRM #19: the copy and prize the mobile home card renders.
    sprint_title_ru: str | None = None
    sprint_title_kk: str | None = None
    sprint_prize_amount: int | None = None
    sprint_access_url: str | None = None
    updated_at: datetime
    updated_by: str | None = None

    model_config = {"from_attributes": True}


class LeaderboardPointsSettingsUpdateDTO(BaseModel):
    """PARTIAL update — every field is optional and only the ones actually
    present in the request body are applied (`model_dump(exclude_unset=True)`
    in the service). Two admin screens write to this endpoint and each owns
    a different subset: the Users page owns the auto-reset cadence, the
    Tournament→Sprint page owns the threshold, prize and card copy. Making
    it a full overwrite would let whichever page saved last silently reset
    the other page's fields to their defaults.

    Explicit `null` IS meaningful and clears the field — that is how the
    admin turns the threshold or prize off — hence Optional rather than
    just having defaults."""

    auto_reset_enabled: bool | None = None
    reset_mode: ResetMode | None = None
    # Ignored when reset_mode == "weekly_monday", but still validated/stored
    # so switching back to "interval" restores the previous cadence.
    interval_days: int | None = Field(default=None, ge=1, le=3650)
    # None/0 disables the sprint-winner threshold entirely.
    sprint_target_points: int | None = Field(default=None, ge=0, le=1_000_000)
    sprint_title_ru: str | None = Field(default=None, max_length=120)
    sprint_title_kk: str | None = Field(default=None, max_length=120)
    # Whole tenge. None/0 == no prize configured.
    sprint_prize_amount: int | None = Field(default=None, ge=0, le=1_000_000_000)
    # Link the "Купить доступ" button opens. None clears it.
    sprint_access_url: str | None = Field(default=None, max_length=500)


class PointsAdjustDTO(BaseModel):
    delta: int
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("delta")
    @classmethod
    def _validate_delta(cls, v: int) -> int:
        if v == 0:
            raise ValueError("delta must not be 0")
        return v


class PointsAdjustResultDTO(BaseModel):
    user_id: str
    points_before: int
    points_after: int
    points_delta: int


class PointsResetResultDTO(BaseModel):
    ran: bool
    users_reset: int = 0
    next_reset_at: datetime | None = None


class SprintWinnerDTO(BaseModel):
    """Public shape of the current week's locked-in sprint winner —
    used by GET /leaderboard/sprint. Name/avatar are resolved the same
    way as the rest of the leaderboard (user_display snapshot / Keycloak
    fallback), not re-derived here."""

    user_id: str
    name: str
    avatar_url: str | None = None
    points_at_win: int
    won_at: datetime


# How a week's winner was decided — mirrors
# `leaderboard_points.models.RESOLUTION_*`.
SprintResolution = Literal["threshold", "closest", "tie_pending", "tie_split"]


class SprintParticipantDTO(BaseModel):
    """One entry on the admin-curated allowlist. `user_id` is NULL while
    the phone has no matching account yet (entry granted in advance);
    `user_display` is then None too and the admin sees the raw number."""

    id: int
    phone_number: str
    user_id: str | None = None
    user_display: str | None = None
    added_by_display: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SprintParticipantCreateDTO(BaseModel):
    """Either identifies an existing account (`user_id`, from the admin's
    user search) or grants entry to a bare phone number typed by hand.
    `phone_number` is required in both cases — it is the table's key, and
    for the user-search path the caller passes the account's own number."""

    phone_number: str = Field(..., min_length=10, max_length=20)
    user_id: str | None = None


class SprintStandingDTO(BaseModel):
    """A participant's position in the CURRENT week — computed live from
    `points_audit_log`, never stored."""

    user_id: str
    name: str
    avatar_url: str | None = None
    points: int


class SprintWinnerEntryDTO(BaseModel):
    """A recorded winner row. `prize_share` is NULL for `tie_pending`
    (nothing awarded until the admin resolves the tie) and for weeks with
    no prize configured."""

    user_id: str
    name: str
    points: int
    resolution_type: SprintResolution
    prize_share: int | None = None
    won_at: datetime


class SprintCurrentDTO(BaseModel):
    """Admin view of the week in progress: what is configured, who is
    competing and who (if anyone) has already been locked in."""

    week_start_at: datetime
    week_end_at: datetime
    target_points: int | None = None
    prize_amount: int | None = None
    participant_count: int
    winners: list[SprintWinnerEntryDTO] = Field(default_factory=list)
    standings: list[SprintStandingDTO] = Field(default_factory=list)


class SprintHistoryEntryDTO(SprintWinnerEntryDTO):
    week_start_at: datetime


class SprintTieResolveResultDTO(BaseModel):
    week_start_at: datetime
    winners_count: int
    prize_share: int | None = None


class WeeklySprintCardDTO(BaseModel):
    """Everything the mobile home card needs, in one request.

    `finished` is true once a threshold winner is locked in for this week:
    the card then swaps its countdown for "Спринт завершён" and shows that
    winner instead of the live leader, so nobody keeps grinding for a prize
    that is already awarded.

    `leader` is None when nobody has scored yet OR when the allowlist is
    empty — the card renders the same reduced layout for both, and for a
    failed request, so the client needs no extra flag to tell them apart."""

    title_ru: str | None = None
    title_kk: str | None = None
    prize_amount: int | None = None
    week_start_at: datetime
    week_end_at: datetime
    participants_total: int
    leader: SprintStandingDTO | None = None
    finished: bool = False


class SprintStandingEntryDTO(BaseModel):
    """One row of the weekly-standings screen. `rank` is 1-based position
    among allowlisted participants who scored this week. `delta` is how
    many places the user moved since the start of today (positive = up,
    negative = down); None means no baseline snapshot yet (first day of
    the week) — the client shows no movement badge."""

    user_id: str
    name: str
    avatar_url: str | None = None
    points: int
    rank: int
    delta: int | None = None


class WeeklyStandingsDTO(BaseModel):
    """Everything the weekly-sprint screen renders in one request.

    `me` is the caller's own row, present only when they are an
    allowlisted participant who has scored — the screen pins it at the top
    and hides it entirely otherwise (a non-participant has no position in a
    contest they are not in). `entries` is the ranked list (top-N)."""

    title_ru: str | None = None
    title_kk: str | None = None
    prize_amount: int | None = None
    week_start_at: datetime
    week_end_at: datetime
    participants_total: int
    finished: bool = False
    # Whether the CALLER is on the allowlist — drives the bottom button:
    # true → "Начать тест", false → "Купить доступ". Independent of `me`,
    # which is null for a participant who simply hasn't scored yet.
    is_participant: bool = False
    # Admin-set link the "Купить доступ" button opens; null hides the button.
    access_url: str | None = None
    me: SprintStandingEntryDTO | None = None
    entries: list[SprintStandingEntryDTO] = Field(default_factory=list)
