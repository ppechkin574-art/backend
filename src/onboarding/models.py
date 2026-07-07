from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class OnboardingStory(Base):
    __tablename__ = "onboarding_stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    priority = Column(Integer, nullable=False, server_default="0")
    is_active = Column(Boolean, nullable=False, server_default="false")
    is_mandatory = Column(Boolean, nullable=False, server_default="true")
    skip_delay_seconds = Column(Integer, nullable=False, server_default="3")
    # ALL | NEW_USERS
    target_audience = Column(String(20), nullable=False, server_default="ALL")
    new_user_days = Column(Integer, nullable=False, server_default="7")
    # FIRST_OPEN | IMMEDIATE
    trigger = Column(String(20), nullable=False, server_default="FIRST_OPEN")
    immediate_count = Column(Integer, nullable=False, server_default="1")
    max_shows_per_user = Column(Integer, nullable=False, server_default="1")
    # HOME | TRAINER | PROFILE | LEADERBOARD | SUBSCRIPTION
    start_screen = Column(String(50), nullable=False, server_default="HOME")
    # When True, story is only shown to phones listed in ONBOARDING_TEST_PHONES
    is_test = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    steps = relationship(
        "OnboardingStep",
        back_populates="story",
        order_by="OnboardingStep.step_order",
        cascade="all, delete-orphan",
    )


class OnboardingStep(Base):
    __tablename__ = "onboarding_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(Integer, ForeignKey("onboarding_stories.id", ondelete="CASCADE"), nullable=False)
    step_order = Column(Integer, nullable=False)
    mascot_image_url = Column(Text, nullable=True)
    title_ru = Column(Text, nullable=False, server_default="")
    title_kk = Column(Text, nullable=False, server_default="")
    body_ru = Column(Text, nullable=False, server_default="")
    body_kk = Column(Text, nullable=False, server_default="")
    # bottom_left | bottom_right | top_left | top_right
    mascot_position = Column(String(20), nullable=False, server_default="bottom_left")
    spotlight_element_key = Column(String(100), nullable=True)
    action_label_ru = Column(Text, nullable=True)
    action_label_kk = Column(Text, nullable=True)
    action_route = Column(Text, nullable=True)
    mascot_scale    = Column(Float, nullable=False, server_default="1.0")
    mascot_x        = Column(Float, nullable=False, server_default="0.0")
    mascot_y        = Column(Float, nullable=False, server_default="0.0")
    mascot_rotation = Column(Float, nullable=False, server_default="0.0")
    bubble_x        = Column(Float, nullable=False, server_default="0.0")
    bubble_y        = Column(Float, nullable=False, server_default="0.0")
    mascot_flip_h   = Column(Boolean, nullable=False, server_default="false")
    mascot_flip_v   = Column(Boolean, nullable=False, server_default="false")

    story = relationship("OnboardingStory", back_populates="steps")


class UserOnboardingView(Base):
    __tablename__ = "user_onboarding_views"
    __table_args__ = (UniqueConstraint("user_id", "story_id", name="uq_user_story"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    story_id = Column(Integer, ForeignKey("onboarding_stories.id", ondelete="CASCADE"), nullable=False)
    view_count = Column(Integer, nullable=False, server_default="0")
    completed_at = Column(DateTime(timezone=True), nullable=True)
    skipped_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
