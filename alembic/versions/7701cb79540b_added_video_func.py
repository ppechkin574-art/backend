"""add video to blocktype enum

Revision ID: 7701cb79540b
Revises: 84749c3a9100
Create Date: 2025-12-06 13:27:39.349740

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7701cb79540b"
down_revision: Union[str, Sequence[str], None] = "84749c3a9100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'video'
                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'blocktype')
            ) THEN
                ALTER TYPE blocktype ADD VALUE 'video';
            END IF;
        END $$;
    """
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
