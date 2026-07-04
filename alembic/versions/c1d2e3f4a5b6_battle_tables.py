"""battle_tables

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6, 1338a104083a, 420aa383195e
Create Date: 2026-07-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: tuple[str, ...] = ("a1b2c3d4e5f6", "1338a104083a", "420aa383195e")
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "battle_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("player1_id", sa.String(), nullable=False),
        sa.Column("player2_id", sa.String(), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("bot_name", sa.String(), nullable=True),
        sa.Column("bot_win_rate", sa.Integer(), nullable=True),
        sa.Column("subject_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("question_data", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="searching"),
        sa.Column("winner_id", sa.String(), nullable=True),
        sa.Column("player1_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("player2_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stars_player1", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stars_player2", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_battle_sessions_player1_id", "battle_sessions", ["player1_id"])
    op.create_index("ix_battle_sessions_status", "battle_sessions", ["status"])

    op.create_table(
        "battle_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("battle_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_battle_answers_session_id", "battle_answers", ["session_id"])


def downgrade() -> None:
    op.drop_table("battle_answers")
    op.drop_table("battle_sessions")
