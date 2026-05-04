"""add_user_relationships_table

Revision ID: 03b64ebd7b20
Revises: 1338a104083a
Create Date: 2026-05-03 10:10:29.414779

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "03b64ebd7b20"
down_revision: Union[str, Sequence[str], None] = "1338a104083a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "user_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "child_id", name="uq_parent_child"),
        sa.Index("idx_relationship_status", "status"),
        sa.Index("idx_user_relationships_parent_id", "parent_id"),
        sa.Index("idx_user_relationships_child_id", "child_id"),
    )


def downgrade():
    op.drop_table("user_relationships")
