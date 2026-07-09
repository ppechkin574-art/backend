"""add bubble and button size to onboarding steps

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5, 2a5acb79a88d, a1f0e7e3b4c2, d3e4f5a6b7c8, f1a2b3c4d5e6, ba77100000001
Create Date: 2026-07-08 12:00:00.000000

"""

from typing import Sequence, Tuple, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[Tuple[str, ...], None] = (
    'a0b1c2d3e4f5',
    '2a5acb79a88d',
    'a1f0e7e3b4c2',
    'd3e4f5a6b7c8',
    'f1a2b3c4d5e6',
    'ba77100000001',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('onboarding_steps', sa.Column('bubble_width', sa.Float(), nullable=False, server_default='260'))
    op.add_column('onboarding_steps', sa.Column('bubble_padding', sa.Float(), nullable=False, server_default='20'))
    op.add_column('onboarding_steps', sa.Column('button_width', sa.Float(), nullable=False, server_default='0'))
    op.add_column('onboarding_steps', sa.Column('button_padding_v', sa.Float(), nullable=False, server_default='15'))


def downgrade() -> None:
    op.drop_column('onboarding_steps', 'button_padding_v')
    op.drop_column('onboarding_steps', 'button_width')
    op.drop_column('onboarding_steps', 'bubble_padding')
    op.drop_column('onboarding_steps', 'bubble_width')
