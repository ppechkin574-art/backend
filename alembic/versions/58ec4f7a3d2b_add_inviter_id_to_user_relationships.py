"""add_inviter_id_to_user_relationships

Revision ID: 58ec4f7a3d2b
Revises: 03b64ebd7b20
Create Date: 2026-05-03 18:37:57.196378

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "58ec4f7a3d2b"
down_revision: Union[str, Sequence[str], None] = "03b64ebd7b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "user_relationships",
        sa.Column("inviter_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_index("idx_inviter_id", "user_relationships", ["inviter_id"])


def downgrade():
    op.drop_index("idx_inviter_id", table_name="user_relationships")
    op.drop_column("user_relationships", "inviter_id")
