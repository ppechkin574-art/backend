import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class CardStyle(Base):
    __tablename__ = "card_styles"

    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    accounts = relationship("UserBankAccount", back_populates="card_style")


class UserBankAccount(Base):
    __tablename__ = "user_bank_accounts"

    guid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_guid = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    card_style_id = Column(Integer, ForeignKey("card_styles.id"), nullable=False)
    card_number = Column(String(16), unique=True, nullable=False)
    balance = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    card_style = relationship("CardStyle", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account", cascade="all, delete-orphan")
    withdrawal_requests = relationship("WithdrawalRequest", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_bank_account_student", "student_guid"),)


class TransactionType(enum.Enum):
    deposit = "deposit"
    withdrawal = "withdrawal"


class TransactionStatus(enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Transaction(Base):
    __tablename__ = "transactions"

    guid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("user_bank_accounts.guid", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(Enum(TransactionType), nullable=False)
    amount = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.completed, nullable=False)
    additional_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account = relationship("UserBankAccount", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_account", "account_guid"),
        Index("ix_transactions_created", "created_at"),
    )


class WithdrawalRequestStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    guid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_guid = Column(
        UUID(as_uuid=True),
        ForeignKey("user_bank_accounts.guid", ondelete="CASCADE"),
        nullable=False,
    )
    amount = Column(Integer, nullable=False)
    iban = Column(String(50), nullable=False)
    card_number = Column(String(16), nullable=False)
    card_holder = Column(String(200), nullable=False)
    iin = Column(String(12), nullable=False)
    status = Column(
        Enum(WithdrawalRequestStatus),
        default=WithdrawalRequestStatus.pending,
        nullable=False,
    )
    admin_comment = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account = relationship("UserBankAccount", back_populates="withdrawal_requests")

    __table_args__ = (
        Index("ix_withdrawal_requests_account", "account_guid"),
        Index("ix_withdrawal_requests_status", "status"),
        Index("ix_withdrawal_requests_created", "created_at"),
    )
