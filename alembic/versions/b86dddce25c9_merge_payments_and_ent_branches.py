"""merge payments and ent branches

Revision ID: b86dddce25c9
Revises: 31bc4873c94a, 90b8e4de3431
Create Date: 2025-09-22 21:02:06.372779

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b86dddce25c9"
down_revision: Union[str, Sequence[str], None] = ("31bc4873c94a", "90b8e4de3431")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
