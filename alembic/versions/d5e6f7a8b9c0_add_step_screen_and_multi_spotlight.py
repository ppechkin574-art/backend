"""add step_screen and spotlight_element_keys to onboarding_steps

Revision ID: d5e6f7a8b9c0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = ("e4f5a6b7c8d9", "a7b8c9d0e1f2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_steps",
        sa.Column("step_screen", sa.String(50), nullable=True),
    )
    op.add_column(
        "onboarding_steps",
        sa.Column(
            "spotlight_element_keys",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    # Migrate existing single key → array
    op.execute(sa.text("""
        UPDATE onboarding_steps
        SET spotlight_element_keys = to_json(ARRAY[spotlight_element_key])
        WHERE spotlight_element_key IS NOT NULL AND spotlight_element_key != ''
    """))


def downgrade() -> None:
    op.drop_column("onboarding_steps", "spotlight_element_keys")
    op.drop_column("onboarding_steps", "step_screen")
