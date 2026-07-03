"""add onboarding tables

Revision ID: a8b7c6d5e4f3
Revises: 316e8e84c074
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a8b7c6d5e4f3"
down_revision = "316e8e84c074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_stories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("skip_delay_seconds", sa.Integer(), server_default="3", nullable=False),
        sa.Column("target_audience", sa.String(20), server_default="ALL", nullable=False),
        sa.Column("new_user_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("trigger", sa.String(20), server_default="FIRST_OPEN", nullable=False),
        sa.Column("immediate_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_shows_per_user", sa.Integer(), server_default="1", nullable=False),
        sa.Column("start_screen", sa.String(50), server_default="HOME", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "onboarding_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("mascot_image_url", sa.Text(), nullable=True),
        sa.Column("title_ru", sa.Text(), server_default="", nullable=False),
        sa.Column("title_kk", sa.Text(), server_default="", nullable=False),
        sa.Column("body_ru", sa.Text(), server_default="", nullable=False),
        sa.Column("body_kk", sa.Text(), server_default="", nullable=False),
        sa.Column("mascot_position", sa.String(20), server_default="bottom_left", nullable=False),
        sa.Column("spotlight_element_key", sa.String(100), nullable=True),
        sa.Column("action_label_ru", sa.Text(), nullable=True),
        sa.Column("action_label_kk", sa.Text(), nullable=True),
        sa.Column("action_route", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["story_id"], ["onboarding_stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_onboarding_views",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["onboarding_stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "story_id", name="uq_user_story"),
    )

    op.create_index("ix_onboarding_stories_is_active", "onboarding_stories", ["is_active"])
    op.create_index("ix_onboarding_stories_priority", "onboarding_stories", ["priority"])
    op.create_index("ix_onboarding_steps_story_id", "onboarding_steps", ["story_id"])
    op.create_index("ix_user_onboarding_views_user_id", "user_onboarding_views", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_onboarding_views")
    op.drop_table("onboarding_steps")
    op.drop_table("onboarding_stories")
