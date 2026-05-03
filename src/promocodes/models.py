from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.enums import PlanType
from database import Base


class Promocode(Base):
    __tablename__ = "promocodes"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False)
    description = Column(String(255))

    plan_type = Column(
        SQLEnum(PlanType),
        nullable=False,
        default=PlanType.PRO.value,
        server_default=PlanType.PRO.value,
    )

    duration_days = Column(Integer, nullable=False)
    max_activations = Column(Integer, nullable=False)
    activations_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True))
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    is_trial = Column(Boolean, default=False)

    is_reusable = Column(Boolean, default=False)

    @classmethod
    def create_from_dict(cls, data: dict):
        """Создать промокод из словаря с валидацией plan_type"""
        if "plan_type" in data and isinstance(data["plan_type"], str):
            data["plan_type"] = PlanType(data["plan_type"].upper())
        return cls(**data)


class PromocodeUsage(Base):
    __tablename__ = "promocode_usages"

    id = Column(Integer, primary_key=True)
    promocode_id = Column(Integer, ForeignKey("promocodes.id"), nullable=False)
    student_guid = Column(UUID(as_uuid=True), nullable=False)
    activated_at = Column(DateTime(timezone=True), server_default=func.now())
    access_expires_at = Column(DateTime(timezone=True), nullable=False)

    activated_plan = Column(SQLEnum(PlanType), nullable=False, default=PlanType.PRO.value)

    promocode = relationship("Promocode", backref="usages")
