import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from database import Base


class FraudEvent(Base):
    __tablename__ = "fraud_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    device_id = Column(String(255), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True, index=True)
    endpoint = Column(String(500), nullable=True)
    method = Column(String(10), nullable=True)
    user_agent = Column(String(500), nullable=True)
    event_type = Column(String(100), nullable=False, index=True)
    reason = Column(String(1000), nullable=True)
    risk_score = Column(Integer, default=0)
    event_metadata = Column("metadata", JSONB, default={})
    status = Column(String(20), default="open", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(255), nullable=True)


class UserRiskProfile(Base):
    __tablename__ = "user_risk_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    current_risk_score = Column(Integer, default=0)
    status = Column(String(20), default="normal", index=True)
    last_suspicious_activity_at = Column(DateTime(timezone=True), nullable=True)
    total_suspicious_events = Column(Integer, default=0)
    restricted_until = Column(DateTime(timezone=True), nullable=True)
    blocked_at = Column(DateTime(timezone=True), nullable=True)
    restriction_reason = Column(String(500), nullable=True)
    is_watchlisted = Column(Boolean, default=False, nullable=False, server_default="false")
    points_frozen = Column(Boolean, default=False, nullable=False, server_default="false")
    referral_disabled = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PointsAuditLog(Base):
    __tablename__ = "points_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    points_before = Column(Integer, nullable=False)
    points_after = Column(Integer, nullable=False)
    points_delta = Column(Integer, nullable=False)
    source_type = Column(String(50), nullable=False)
    source_id = Column(String(100), nullable=True)
    reason = Column(String(500), nullable=True)
    is_suspicious = Column(Boolean, default=False, index=True)
    fraud_event_id = Column(
        Integer, ForeignKey("fraud_events.id"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
