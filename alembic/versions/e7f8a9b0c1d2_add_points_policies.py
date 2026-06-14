"""Add points_policies table — admin-configurable leaderboard award rules

Each of the four activity types (ent_full, ent_subject, trainer, daily_test)
gets one seeded row. Initial seed mirrors the current hardcoded behaviour:
- ent_full: enabled, score_based (1× correct answers), always, no threshold
- ent_subject / trainer / daily_test: disabled (no change to existing behaviour)

Admins can update mode, fixed_points, score_multiplier, min_score_percent,
and repeat_mode via the admin panel at PUT /admin/points-policies/{type}.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-14
"""

from typing import Union, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "points_policies",
        sa.Column("activity_type", sa.String(30), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mode", sa.String(15), nullable=False, server_default="fixed"),
        sa.Column("fixed_points", sa.Integer(), nullable=True),
        sa.Column("score_multiplier", sa.Float(), nullable=True, server_default="1.0"),
        sa.Column("min_score_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeat_mode", sa.String(20), nullable=False, server_default="always"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Seed initial rows — must exactly match current hardcoded behaviour so
    # existing production traffic is unaffected after the deploy.
    op.execute("""
        INSERT INTO points_policies
            (activity_type, is_enabled, mode, fixed_points, score_multiplier, min_score_percent, repeat_mode)
        VALUES
            ('ent_full',    TRUE,  'score_based', NULL, 1.0, 0, 'always'),
            ('ent_subject', FALSE, 'fixed',        0,   NULL, 0, 'always'),
            ('trainer',     FALSE, 'fixed',        0,   NULL, 0, 'always'),
            ('daily_test',  FALSE, 'fixed',        0,   NULL, 0, 'always')
    """)


def downgrade() -> None:
    op.drop_table("points_policies")
