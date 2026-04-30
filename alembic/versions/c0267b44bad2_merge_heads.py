"""merge heads

Revision ID: c0267b44bad2
Revises: 2b750c0f99de, 6f3a6e970b9f
Create Date: 2025-12-09 12:29:24.143569

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c0267b44bad2"
down_revision: Union[str, Sequence[str], None] = ("2b750c0f99de", "6f3a6e970b9f")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
