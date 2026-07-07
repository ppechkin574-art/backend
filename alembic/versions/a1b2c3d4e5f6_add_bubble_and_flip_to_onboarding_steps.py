"""add bubble position and mascot flip to onboarding_steps

Revision ID: a1b2c3d4e5f6
Revises: f1e2d3c4b5a6
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_steps",
        sa.Column("bubble_x", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("bubble_y", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_flip_h", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_flip_v", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("onboarding_steps", "mascot_flip_v")
    op.drop_column("onboarding_steps", "mascot_flip_h")
    op.drop_column("onboarding_steps", "bubble_y")
    op.drop_column("onboarding_steps", "bubble_x")
