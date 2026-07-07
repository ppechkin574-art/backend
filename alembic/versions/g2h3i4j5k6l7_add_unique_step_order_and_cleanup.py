"""add unique constraint on step_order per story

Revision ID: g2h3i4j5k6l7
Revises: f1e2d3c4b5a6
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "g2h3i4j5k6l7"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_step_story_order",
        "onboarding_steps",
        ["story_id", "step_order"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_step_story_order", "onboarding_steps", type_="unique")
