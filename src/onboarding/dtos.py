from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MascotPosition = Literal["bottom_left", "bottom_right", "top_left", "top_right"]
TargetAudience = Literal["ALL", "NEW_USERS"]
TriggerType    = Literal["FIRST_OPEN", "IMMEDIATE"]
StartScreen    = Literal["HOME", "TRAINER", "PROFILE", "LEADERBOARD", "SUBSCRIPTION"]


# ─── Step DTOs ───────────────────────────────────────────────────────────────

class OnboardingStepDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    step_order: int
    mascot_image_url: Optional[str] = None
    title_ru: str
    title_kk: str
    body_ru: str
    body_kk: str
    mascot_position: str
    spotlight_element_key: Optional[str] = None
    action_label_ru: Optional[str] = None
    action_label_kk: Optional[str] = None
    action_route: Optional[str] = None
    mascot_scale: float = 1.0
    mascot_x: float = 0.0
    mascot_y: float = 0.0
    mascot_rotation: float = 0.0
    bubble_x: float = 0.0
    bubble_y: float = 0.0
    mascot_flip_h: bool = False
    mascot_flip_v: bool = False
    step_screen: Optional[str] = None
    spotlight_element_keys: List[str] = Field(default_factory=list)
    spotlight_adjustments: Dict[str, Any] = Field(default_factory=dict)


class OnboardingStepCreateDTO(BaseModel):
    step_order: int = Field(ge=1)
    mascot_image_url: Optional[str] = None
    title_ru: str = Field(default="", max_length=300)
    title_kk: str = Field(default="", max_length=300)
    body_ru: str = Field(default="", max_length=1000)
    body_kk: str = Field(default="", max_length=1000)
    mascot_position: MascotPosition = "bottom_left"
    spotlight_element_key: Optional[str] = Field(default=None, max_length=100)
    action_label_ru: Optional[str] = Field(default=None, max_length=200)
    action_label_kk: Optional[str] = Field(default=None, max_length=200)
    action_route: Optional[str] = Field(default=None, max_length=200)
    mascot_scale: float = Field(default=1.0, ge=0.3, le=3.0)
    mascot_x: float = Field(default=0.0, ge=-200.0, le=200.0)
    mascot_y: float = Field(default=0.0, ge=-200.0, le=200.0)
    mascot_rotation: float = Field(default=0.0, ge=-180.0, le=180.0)
    bubble_x: float = Field(default=0.0, ge=-200.0, le=200.0)
    bubble_y: float = Field(default=0.0, ge=-200.0, le=200.0)
    mascot_flip_h: bool = False
    mascot_flip_v: bool = False
    step_screen: Optional[str] = Field(default=None, max_length=50)
    spotlight_element_keys: List[str] = Field(default_factory=list)
    spotlight_adjustments: Dict[str, Any] = Field(default_factory=dict)


class OnboardingStepUpdateDTO(BaseModel):
    step_order: Optional[int] = Field(default=None, ge=1)
    mascot_image_url: Optional[str] = None
    title_ru: Optional[str] = Field(default=None, max_length=300)
    title_kk: Optional[str] = Field(default=None, max_length=300)
    body_ru: Optional[str] = Field(default=None, max_length=1000)
    body_kk: Optional[str] = Field(default=None, max_length=1000)
    mascot_position: Optional[MascotPosition] = None
    spotlight_element_key: Optional[str] = Field(default=None, max_length=100)
    action_label_ru: Optional[str] = Field(default=None, max_length=200)
    action_label_kk: Optional[str] = Field(default=None, max_length=200)
    action_route: Optional[str] = Field(default=None, max_length=200)
    mascot_scale: Optional[float] = Field(default=None, ge=0.3, le=3.0)
    mascot_x: Optional[float] = Field(default=None, ge=-200.0, le=200.0)
    mascot_y: Optional[float] = Field(default=None, ge=-200.0, le=200.0)
    mascot_rotation: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    bubble_x: Optional[float] = Field(default=None, ge=-200.0, le=200.0)
    bubble_y: Optional[float] = Field(default=None, ge=-200.0, le=200.0)
    mascot_flip_h: Optional[bool] = None
    mascot_flip_v: Optional[bool] = None
    step_screen: Optional[str] = Field(default=None, max_length=50)
    spotlight_element_keys: Optional[List[str]] = None
    spotlight_adjustments: Optional[Dict[str, Any]] = None


# ─── Story DTOs ──────────────────────────────────────────────────────────────

class OnboardingStoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    priority: int
    is_active: bool
    is_mandatory: bool
    is_test: bool
    skip_delay_seconds: int
    target_audience: str
    new_user_days: int
    trigger: str
    immediate_count: int
    max_shows_per_user: int
    start_screen: str
    created_at: datetime
    updated_at: datetime
    steps: list[OnboardingStepDTO] = []


class OnboardingStoryCreateDTO(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=0, ge=0)
    is_active: bool = False
    is_mandatory: bool = True
    is_test: bool = False
    skip_delay_seconds: int = Field(default=3, ge=0, le=60)
    target_audience: TargetAudience = "ALL"
    new_user_days: int = Field(default=7, ge=1)
    trigger: TriggerType = "FIRST_OPEN"
    immediate_count: int = Field(default=1, ge=1)
    max_shows_per_user: int = Field(default=1, ge=1)
    start_screen: StartScreen = "HOME"
    steps: list[OnboardingStepCreateDTO] = []


class OnboardingStoryUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    priority: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    is_mandatory: Optional[bool] = None
    is_test: Optional[bool] = None
    skip_delay_seconds: Optional[int] = Field(default=None, ge=0, le=60)
    target_audience: Optional[TargetAudience] = None
    new_user_days: Optional[int] = Field(default=None, ge=1)
    trigger: Optional[TriggerType] = None
    immediate_count: Optional[int] = Field(default=None, ge=1)
    max_shows_per_user: Optional[int] = Field(default=None, ge=1)
    start_screen: Optional[StartScreen] = None
    steps: Optional[list[OnboardingStepCreateDTO]] = None


# ─── App-facing DTOs (public) ────────────────────────────────────────────────

class OnboardingStepPublicDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_order: int
    mascot_image_url: Optional[str] = None
    title_ru: str
    title_kk: str
    body_ru: str
    body_kk: str
    mascot_position: str
    spotlight_element_key: Optional[str] = None
    action_label_ru: Optional[str] = None
    action_label_kk: Optional[str] = None
    action_route: Optional[str] = None
    mascot_scale: float = 1.0
    mascot_x: float = 0.0
    mascot_y: float = 0.0
    mascot_rotation: float = 0.0
    bubble_x: float = 0.0
    bubble_y: float = 0.0
    mascot_flip_h: bool = False
    mascot_flip_v: bool = False
    step_screen: Optional[str] = None
    spotlight_element_keys: List[str] = Field(default_factory=list)
    spotlight_adjustments: Dict[str, Any] = Field(default_factory=dict)


class OnboardingStoryPublicDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    priority: int
    is_mandatory: bool
    is_test: bool
    skip_delay_seconds: int
    target_audience: str
    new_user_days: int
    trigger: str
    immediate_count: int
    max_shows_per_user: int
    start_screen: str
    steps: list[OnboardingStepPublicDTO] = []


# ─── View tracking ───────────────────────────────────────────────────────────

class OnboardingViewDTO(BaseModel):
    story_id: int
    skipped: bool = False


class OnboardingViewResponseDTO(BaseModel):
    story_id: int
    view_count: int
    completed_at: Optional[datetime] = None
    skipped_at: Optional[datetime] = None
