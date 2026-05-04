from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class UserRelationship(Base):
    __tablename__ = "user_relationships"

    id = Column(Integer, primary_key=True)
    inviter_id = Column(
        UUID(as_uuid=True), nullable=False, index=True
    )  # кто отправил приглашение
    parent_id = Column(
        UUID(as_uuid=True), nullable=False, index=True
    )  # всегда родитель (вычисляется)
    child_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # всегда ребёнок
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_parent_child"),
        Index("idx_relationship_status", "status"),
        Index("idx_inviter_id", "inviter_id"),
    )
