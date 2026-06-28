"""Add admin action flags to user_risk_profiles: is_watchlisted, points_frozen, referral_disabled

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_risk_profiles",
        sa.Column("is_watchlisted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "user_risk_profiles",
        sa.Column("points_frozen", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "user_risk_profiles",
        sa.Column("referral_disabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("user_risk_profiles", "referral_disabled")
    op.drop_column("user_risk_profiles", "points_frozen")
    op.drop_column("user_risk_profiles", "is_watchlisted")
