from sqlalchemy import Column, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid

Base = declarative_base()


class UserPoints(Base):
    __tablename__ = "user_points"
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    total_points = Column(Integer, nullable=False, default=0)
