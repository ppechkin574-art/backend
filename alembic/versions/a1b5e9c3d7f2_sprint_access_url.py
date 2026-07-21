"""weekly sprint: admin-set access link for the "Купить доступ" button

CRM #19 — a user who isn't on the sprint allowlist sees a "Купить доступ"
button on the weekly-sprint screen. Entry is granted by the admin, so the
button just opens a link the admin controls (payment page, WhatsApp, etc).
NULL means no link configured and the client hides the button.

Revision ID: a1b5e9c3d7f2
Revises: f8a4d2c6b9e1
Create Date: 2026-07-20 23:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b5e9c3d7f2"
down_revision: Union[str, None] = "f8a4d2c6b9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_points_settings",
        sa.Column("sprint_access_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_points_settings", "sprint_access_url")
