"""add _kk translation fields to events

Revision ID: f1a2b3c4d5e6
Revises: a0b1c2d3e4f5, 420aa383195e, 1338a104083a, d9e0f1a2b3c4
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = ("a0b1c2d3e4f5", "420aa383195e", "1338a104083a", "d9e0f1a2b3c4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("badge_text_kk", sa.String(100), nullable=True))
    op.add_column("events", sa.Column("title_kk", sa.String(300), nullable=True))
    op.add_column("events", sa.Column("prize_text_kk", sa.String(100), nullable=True))
    op.add_column("events", sa.Column("subtitle_kk", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("secondary_text_kk", sa.String(300), nullable=True))
    op.add_column("events", sa.Column("button_text_kk", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "button_text_kk")
    op.drop_column("events", "secondary_text_kk")
    op.drop_column("events", "subtitle_kk")
    op.drop_column("events", "prize_text_kk")
    op.drop_column("events", "title_kk")
    op.drop_column("events", "badge_text_kk")
