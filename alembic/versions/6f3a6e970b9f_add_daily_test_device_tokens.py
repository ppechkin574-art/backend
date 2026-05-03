"""Add daily test device tokens table

Revision ID: 6f3a6e970b9f
Revises: 95342007a49b
Create Date: 2025-11-17 18:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f3a6e970b9f"
down_revision: Union[str, Sequence[str], None] = "95342007a49b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "daily_test_device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("student_guid", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_guid"], ["students.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token", name="uq_daily_test_device_token"),
    )
    op.create_index(
        "idx_daily_test_device_tokens_student",
        "daily_test_device_tokens",
        ["student_guid"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_daily_test_device_tokens_student", table_name="daily_test_device_tokens"
    )
    op.drop_table("daily_test_device_tokens")
