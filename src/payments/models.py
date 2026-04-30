from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    order_id = Column(String(255), unique=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="KZT")
    status = Column(String(32), default="created")
    pg_payment_id = Column(String(255), nullable=True)
    pg_redirect_url = Column(Text, nullable=True)

    pg_status_code = Column(String(255), nullable=True)
    pg_status_desc = Column(Text, nullable=True)

    is_subscription_payment = Column(Boolean, default=False)
    subscription_plan = Column(String(32), nullable=True)

    pg_payment_method = Column(String(255), nullable=True)
    pg_net_amount = Column(Numeric(12, 2), nullable=True)
    pg_ps_amount = Column(Numeric(12, 2), nullable=True)
    pg_ps_currency = Column(String(10), nullable=True)
    pg_ps_full_amount = Column(Numeric(12, 2), nullable=True)
    pg_result = Column(Integer, nullable=True)

    pg_card_pan = Column(String(64), nullable=True)
    pg_card_brand = Column(String(64), nullable=True)
    pg_card_exp = Column(String(10), nullable=True)
    pg_card_owner = Column(String(255), nullable=True)
    pg_auth_code = Column(String(64), nullable=True)

    pg_reference = Column(String(255), nullable=True)
    pg_payment_date = Column(DateTime(timezone=True), nullable=True)

    user_id = Column(String(255), nullable=True)
    pg_user_contact_email = Column(String(320), nullable=True)
    pg_user_ip = Column(String(64), nullable=True)
    pg_user_phone = Column(String(64), nullable=True)

    raw_request = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)

    attempts_count = Column(Integer, default=0)
    last_polled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    status_history = relationship("PaymentStatusHistory", backref="payment", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="payment", uselist=False)


class PaymentStatusHistory(Base):
    __tablename__ = "payment_status_history"

    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    status = Column(String(32))
    created_at = Column(DateTime, server_default=func.now())


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    fp_user_id = Column(String(255), nullable=True)
    card_token = Column(String(255), nullable=False)
    card_pan = Column(String(64), nullable=True)
    card_brand = Column(String(32), nullable=True)
    card_exp = Column(String(10), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
