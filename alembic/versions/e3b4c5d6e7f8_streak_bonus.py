"""Daily streak bonus — reward tiers + claim history

Tables backing the «при входе раз в день +X монет» feature:
- `streak_reward_tiers`  operator-editable thresholds
- `streak_bonus_claims`  one row per user per local-KZ day

Seeds three default tiers so the iOS modal lands on something at
first open: 100 / 200 / 500 coins at day 1 / 7 / 30. Operator
tweaks from the admin panel.

Revision ID: e3b4c5d6e7f8
Revises: d2a3b4c5d6e7
Create Date: 2026-05-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b4c5d6e7f8"
down_revision: Union[str, None] = "d2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "streak_reward_tiers",
        sa.Column("min_streak", sa.Integer, primary_key=True),
        sa.Column("coins", sa.Integer, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "streak_bonus_claims",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("claim_date", sa.Date, nullable=False),
        sa.Column("streak_at_claim", sa.Integer, nullable=False),
        sa.Column("coins_credited", sa.Integer, nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "claim_date", name="uq_streak_bonus_claims_user_date"
        ),
    )
    op.create_index(
        "ix_streak_bonus_claims_user_id",
        "streak_bonus_claims",
        ["user_id"],
    )

    # Default tiers — operator tunes from /admin/streak-reward-tiers
    op.execute(
        """
        INSERT INTO streak_reward_tiers (min_streak, coins, is_active) VALUES
          (1,  100, true),
          (7,  200, true),
          (30, 500, true)
        ON CONFLICT (min_streak) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_streak_bonus_claims_user_id", table_name="streak_bonus_claims")
    op.drop_table("streak_bonus_claims")
    op.drop_table("streak_reward_tiers")
