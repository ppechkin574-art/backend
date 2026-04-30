import random
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    CardStyle,
    Transaction,
    TransactionStatus,
    TransactionType,
    UserBankAccount,
    WithdrawalRequest,
    WithdrawalRequestStatus,
)


class BankRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_all_card_styles(self, only_active: bool = True) -> list[CardStyle]:
        query = select(CardStyle)
        if only_active:
            query = query.where(CardStyle.is_active)
        return self._session.execute(query).scalars().all()

    def get_card_style_by_id(self, style_id: int) -> CardStyle | None:
        return self._session.get(CardStyle, style_id)

    def create_card_style(self, **kwargs) -> CardStyle:
        style = CardStyle(**kwargs)
        self._session.add(style)
        self._session.flush()
        return style

    def update_card_style(self, style_id: int, **kwargs) -> CardStyle | None:
        style = self.get_card_style_by_id(style_id)
        if not style:
            return None
        for key, value in kwargs.items():
            setattr(style, key, value)
        self._session.flush()
        return style

    def delete_card_style(self, style_id: int) -> bool:
        style = self.get_card_style_by_id(style_id)
        if not style:
            return False
        self._session.delete(style)
        self._session.flush()
        return True

    def get_account_by_student(self, student_guid: UUID) -> UserBankAccount | None:
        return self._session.execute(
            select(UserBankAccount).where(UserBankAccount.student_guid == student_guid)
        ).scalar_one_or_none()

    def get_account_by_guid(self, account_guid: UUID) -> UserBankAccount | None:
        return self._session.get(UserBankAccount, account_guid)

    def create_account(self, student_guid: UUID, card_style_id: int, card_number: str) -> UserBankAccount:
        account = UserBankAccount(
            student_guid=student_guid,
            card_style_id=card_style_id,
            card_number=card_number,
            balance=0,
        )
        self._session.add(account)
        self._session.flush()
        return account

    def update_account_style(self, account_guid: UUID, card_style_id: int) -> UserBankAccount | None:
        account = self.get_account_by_guid(account_guid)
        if account:
            account.card_style_id = card_style_id
            self._session.flush()
        return account

    def update_account_balance(self, account_guid: UUID, delta: int) -> UserBankAccount | None:
        account = self.get_account_by_guid(account_guid)
        if account:
            account.balance += delta
            self._session.flush()
        return account

    def create_transaction(
        self,
        account_guid: UUID,
        _type: TransactionType,
        amount: int,
        description: str | None = None,
        status: TransactionStatus = TransactionStatus.completed,
        additional_metadata: str | None = None,
    ) -> Transaction:
        tx = Transaction(
            account_guid=account_guid,
            type=_type,
            amount=amount,
            description=description,
            status=status,
            additional_metadata=additional_metadata,
        )
        self._session.add(tx)
        self._session.flush()
        return tx

    def get_transactions_by_account(self, account_guid: UUID, limit: int = 100) -> list[Transaction]:
        return (
            self._session.execute(
                select(Transaction)
                .where(Transaction.account_guid == account_guid)
                .order_by(Transaction.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_transaction_by_guid(self, transaction_guid: UUID) -> Transaction | None:
        return self._session.get(Transaction, transaction_guid)

    def create_withdrawal_request(
        self,
        account_guid: UUID,
        amount: int,
        iban: str,
        card_number: str,
        card_holder: str,
        iin: str,
    ) -> WithdrawalRequest:
        request = WithdrawalRequest(
            account_guid=account_guid,
            amount=amount,
            iban=iban,
            card_number=card_number,
            card_holder=card_holder,
            iin=iin,
        )
        self._session.add(request)
        self._session.flush()
        return request

    def get_withdrawal_request_by_guid(self, request_guid: UUID) -> WithdrawalRequest | None:
        return self._session.get(WithdrawalRequest, request_guid)

    def get_withdrawal_requests_by_account(self, account_guid: UUID) -> list[WithdrawalRequest]:
        return (
            self._session.execute(
                select(WithdrawalRequest)
                .where(WithdrawalRequest.account_guid == account_guid)
                .order_by(WithdrawalRequest.created_at.desc())
            )
            .scalars()
            .all()
        )

    def get_pending_withdrawal_requests(self, limit: int = 100) -> list[WithdrawalRequest]:
        return (
            self._session.execute(
                select(WithdrawalRequest)
                .where(WithdrawalRequest.status == WithdrawalRequestStatus.pending)
                .order_by(WithdrawalRequest.created_at.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def update_withdrawal_request_status(
        self,
        request_guid: UUID,
        status: WithdrawalRequestStatus,
        admin_comment: str | None = None,
        processed_at: datetime | None = None,
    ) -> WithdrawalRequest | None:
        request = self.get_withdrawal_request_by_guid(request_guid)
        if not request:
            return None
        request.status = status
        if admin_comment is not None:
            request.admin_comment = admin_comment
        request.processed_at = processed_at or datetime.now(UTC)
        self._session.flush()
        return request

    def generate_unique_card_number(self) -> str:
        while True:
            number = "".join(str(random.randint(0, 9)) for _ in range(16))  # noqa S311
            exists = self._session.execute(select(UserBankAccount).where(UserBankAccount.card_number == number)).first()
            if not exists:
                return number

    def get_sum_pending_withdrawal_requests(self, account_guid: UUID) -> int:
        """Возвращает сумму всех pending заявок для указанного аккаунта."""
        result = self._session.execute(
            select(func.coalesce(func.sum(WithdrawalRequest.amount), 0)).where(
                WithdrawalRequest.account_guid == account_guid,
                WithdrawalRequest.status == WithdrawalRequestStatus.pending,
            )
        ).scalar()
        return result or 0
