"""add is_test to onboarding_stories

Revision ID: d9e0f1a2b3c4
Revises: c9d0e1f2a3b4
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa

revision = "d9e0f1a2b3c4"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_stories",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("onboarding_stories", "is_test")
