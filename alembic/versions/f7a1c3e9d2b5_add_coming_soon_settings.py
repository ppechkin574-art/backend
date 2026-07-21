"""add coming_soon_settings (admin-editable «Скоро запускаем» copy)

Single-row table for the coming-soon screen title (2 parts) and subtitle in
RU + KK — text that used to be hardcoded l10n strings. Seeds one row with the
current defaults so the app has copy immediately (the read path also
get_or_creates, this is just to avoid an empty first render).

Revision ID: f7a1c3e9d2b5
Revises: e5f9a3b7c2d4
Create Date: 2026-07-21 06:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c3e9d2b5"
down_revision: Union[str, None] = "e5f9a3b7c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coming_soon_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title1_ru", sa.String(length=200), server_default="Скоро ", nullable=False),
        sa.Column("title1_kk", sa.String(length=200), server_default="Жақында ", nullable=False),
        sa.Column("title2_ru", sa.String(length=200), server_default="запускаем!", nullable=False),
        sa.Column("title2_kk", sa.String(length=200), server_default="іске қосамыз!", nullable=False),
        sa.Column("subtitle_ru", sa.Text(), nullable=False),
        sa.Column("subtitle_kk", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO coming_soon_settings
            (title1_ru, title1_kk, title2_ru, title2_kk, subtitle_ru, subtitle_kk)
        VALUES (
            'Скоро ', 'Жақында ', 'запускаем!', 'іске қосамыз!',
            '«{title}» откроется совсем скоро.' || chr(10) || 'Мы сообщим тебе первому.',
            '«{title}» жақын арада ашылады.' || chr(10) || 'Біз сізге бірінші хабарлаймыз.'
        )
        """
    )


def downgrade() -> None:
    op.drop_table("coming_soon_settings")
