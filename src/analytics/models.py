import uuid

from sqlalchemy import TIMESTAMP, UUID, BigInteger, Column, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB

from database import Base


class UserActivity(Base):
    __tablename__ = "user_activity"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=True, index=True)
    device_id = Column(String(255), nullable=False, index=True)
    session_id = Column(String(255), nullable=False, index=True)
    event_name = Column(String(100), nullable=False, index=True)
    event_time = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)
    platform = Column(String(50))
    app_version = Column(String(50))
    os_version = Column(String(50))
    country = Column(String(100))
    city = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    meta = Column(JSONB, default={})
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
