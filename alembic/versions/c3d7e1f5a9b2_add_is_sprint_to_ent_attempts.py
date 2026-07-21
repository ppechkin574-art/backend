"""add is_sprint flag to ent_attempts

Isolates the weekly-sprint test from the normal ЕНТ flow. Sprint attempts
reuse the full-exam engine, so without a marker a regular ҰБТ could resume a
leftover sprint attempt (same subjects, within the 240-min window) and its
answers could leak into the global «Кубок» on completion. The flag keeps
sprint attempts out of the active-attempt resume pool and out of ЕНТ
history/stats.

Revision ID: c3d7e1f5a9b2
Revises: b2c6f0d4e8a3
Create Date: 2026-07-21 00:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d7e1f5a9b2"
down_revision: Union[str, None] = "b2c6f0d4e8a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ent_attempts",
        sa.Column(
            "is_sprint",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("ent_attempts", "is_sprint")
