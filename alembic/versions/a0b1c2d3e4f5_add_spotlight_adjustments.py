"""add spotlight_adjustments to onboarding_steps

Revision ID: a0b1c2d3e4f5
Revises: d5e6f7a8b9c0
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "a0b1c2d3e4f5"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_steps",
        sa.Column(
            "spotlight_adjustments",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("onboarding_steps", "spotlight_adjustments")
