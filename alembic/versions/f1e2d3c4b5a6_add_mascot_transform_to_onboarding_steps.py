"""add mascot transform to onboarding_steps

Revision ID: f1e2d3c4b5a6
Revises: ba77100000001
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "f1e2d3c4b5a6"
down_revision = "ba77100000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_scale", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_x", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_y", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column("mascot_rotation", sa.Float(), nullable=False, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("onboarding_steps", "mascot_rotation")
    op.drop_column("onboarding_steps", "mascot_y")
    op.drop_column("onboarding_steps", "mascot_x")
    op.drop_column("onboarding_steps", "mascot_scale")
