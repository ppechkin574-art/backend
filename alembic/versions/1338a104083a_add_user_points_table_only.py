"""add_user_points_table_only

Revision ID: 1338a104083a
Revises: bdab54e499a9
Create Date: 2026-05-02 ...
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "1338a104083a"
down_revision = "bdab54e499a9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_points",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    op.drop_table("user_points")
