"""add payments tables

Revision ID: 31bc4873c94a
Revises: e0ff4d7f0a5a
Create Date: 2025-09-12 12:50:17.091518

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "31bc4873c94a"
down_revision: Union[str, Sequence[str], None] = "e0ff4d7f0a5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.String(255), unique=True, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=True, server_default="KZT"),
        sa.Column("status", sa.String(32), nullable=True, server_default="created"),
        sa.Column("pg_payment_id", sa.String(255), nullable=True),
        sa.Column("pg_redirect_url", sa.Text, nullable=True),
        sa.Column("pg_status_code", sa.String(255), nullable=True),
        sa.Column("pg_status_desc", sa.Text, nullable=True),
        sa.Column("pg_payment_method", sa.String(255), nullable=True),
        sa.Column("pg_net_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("pg_ps_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("pg_ps_currency", sa.String(10), nullable=True),
        sa.Column("pg_ps_full_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("pg_result", sa.Integer, nullable=True),
        sa.Column("pg_card_pan", sa.String(64), nullable=True),
        sa.Column("pg_card_brand", sa.String(64), nullable=True),
        sa.Column("pg_card_exp", sa.String(10), nullable=True),
        sa.Column("pg_card_owner", sa.String(255), nullable=True),
        sa.Column("pg_auth_code", sa.String(64), nullable=True),
        sa.Column("pg_reference", sa.String(255), nullable=True),
        sa.Column("pg_payment_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("pg_user_contact_email", sa.String(320), nullable=True),
        sa.Column("pg_user_ip", sa.String(64), nullable=True),
        sa.Column("pg_user_phone", sa.String(64), nullable=True),
        sa.Column("raw_request", sa.Text, nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("attempts_count", sa.Integer, nullable=True, server_default="0"),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            onupdate=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "payment_status_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payment_id", sa.Integer, sa.ForeignKey("payments.id")),
        sa.Column("status", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_status_history")
    op.drop_table("payments")
