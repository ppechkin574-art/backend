"""Security / Anti-Fraud tables: fraud_events, user_risk_profiles, points_audit_log

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- fraud_events ---
    op.create_table(
        "fraud_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("endpoint", sa.String(500), nullable=True),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=True, server_default=sa.text("'open'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fraud_events_user_id", "fraud_events", ["user_id"])
    op.create_index("ix_fraud_events_device_id", "fraud_events", ["device_id"])
    op.create_index("ix_fraud_events_ip_address", "fraud_events", ["ip_address"])
    op.create_index("ix_fraud_events_event_type", "fraud_events", ["event_type"])
    op.create_index("ix_fraud_events_status", "fraud_events", ["status"])
    op.create_index("ix_fraud_events_created_at", "fraud_events", ["created_at"])

    # --- user_risk_profiles ---
    op.create_table(
        "user_risk_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_risk_score", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=True, server_default=sa.text("'normal'")),
        sa.Column("last_suspicious_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_suspicious_events", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("restricted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restriction_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_risk_profiles_user_id"),
    )
    op.create_index("ix_user_risk_profiles_user_id", "user_risk_profiles", ["user_id"])
    op.create_index("ix_user_risk_profiles_status", "user_risk_profiles", ["status"])

    # --- points_audit_log ---
    op.create_table(
        "points_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("points_before", sa.Integer(), nullable=False),
        sa.Column("points_after", sa.Integer(), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("is_suspicious", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("fraud_event_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["fraud_event_id"], ["fraud_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_points_audit_log_user_id", "points_audit_log", ["user_id"])
    op.create_index("ix_points_audit_log_is_suspicious", "points_audit_log", ["is_suspicious"])
    op.create_index("ix_points_audit_log_created_at", "points_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("points_audit_log")
    op.drop_table("user_risk_profiles")
    op.drop_table("fraud_events")
