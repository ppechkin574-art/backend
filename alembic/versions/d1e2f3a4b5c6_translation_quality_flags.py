"""Add quality_flags_kk JSON column to questions for translation review workflow.

Revision ID: d1e2f3a4b5c6
Revises: 9a8b7c6d5e4f
Create Date: 2026-06-21
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "9a8b7c6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("quality_flags_kk", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "quality_flags_kk")
