"""add question explanation columns (memorisation rule, ru/kk)

Backs the post-test review «Запомни» card — a short rule / why the correct
answer is correct, authored in admin, served in review payloads. Two nullable
Text columns on `questions`; existing rows unaffected.

Revision ID: c2a3b4d5e6f7
Revises: b1f2a3c4d5e6
Create Date: 2026-06-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2a3b4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "b1f2a3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("explanation_ru", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("explanation_kk", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "explanation_kk")
    op.drop_column("questions", "explanation_ru")
