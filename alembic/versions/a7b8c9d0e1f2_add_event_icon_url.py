"""add icon_url to events table

Revision ID: a7b8c9d0e1f2
Revises: 316e8e84c074
Create Date: 2026-07-05 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "316e8e84c074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("icon_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "icon_url")
