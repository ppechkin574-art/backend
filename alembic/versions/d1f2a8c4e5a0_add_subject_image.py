"""add subject image column

Revision ID: d1f2a8c4e5a0
Revises: bdab54e499a9
Create Date: 2026-05-01 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d1f2a8c4e5a0"
down_revision: Union[str, Sequence[str], None] = "bdab54e499a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column("image", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("subjects", "image")
