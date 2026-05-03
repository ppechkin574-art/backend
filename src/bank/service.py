import json
import logging
from uuid import UUID

from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

from .dtos import (
    AccountOperationResponseDTO,
    CardStyleCreateDTO,
    CardStyleDTO,
    CardStyleUpdateDTO,
    TransactionDTO,
    UserBankAccountDTO,
    WithdrawalRequestCreateDTO,
    WithdrawalRequestDTO,
    WithdrawalRequestUpdateDTO,
)
from .exceptions import (
    BankAccountNotFound,
    CardStyleNotFound,
    InsufficientBalance,
    InvalidWithdrawalStatus,
    TransactionNotFound,
    WithdrawalAmountTooSmall,
    WithdrawalRequestNotFound,
)
from .models import TransactionStatus, TransactionType, WithdrawalRequestStatus

logger = logging.getLogger(__name__)


class BankService:
    MIN_WITHDRAWAL_AMOUNT = 100

    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="card_styles")
    def get_all_card_styles(self, only_active: bool = True) -> list[CardStyleDTO]:
        with self._uow:
            styles = self._uow.bank.get_all_card_styles(only_active)
            return [
                CardStyleDTO(
                    id=s.id,
                    guid=str(s.guid),
                    name=s.name,
                    is_active=s.is_active,
                )
                for s in styles
            ]

    def create_card_style(self, data: CardStyleCreateDTO) -> CardStyleDTO:
        with self._uow:
            style = self._uow.bank.create_card_style(**data.model_dump())
            self._uow.commit()
            self._cache_service.invalidate_by_resource("card_styles")
            return CardStyleDTO(
                id=style.id,
                guid=str(style.guid),
                name=style.name,
                is_active=style.is_active,
            )

    def get_card_style_by_id(self, style_id: int) -> CardStyleDTO:
        with self._uow:
            style = self._uow.bank.get_card_style_by_id(style_id)
            if not style:
                raise CardStyleNotFound(f"Card style {style_id} not found")
            return CardStyleDTO(
                id=style.id,
                guid=str(style.guid),
                name=style.name,
                is_active=style.is_active,
            )

    def update_card_style(self, style_id: int, data: CardStyleUpdateDTO) -> CardStyleDTO:
        with self._uow:
            style = self._uow.bank.update_card_style(style_id, **data.model_dump(exclude_unset=True))
            if not style:
                raise CardStyleNotFound(f"Card style {style_id} not found")
            self._uow.commit()
            self._cache_service.invalidate_by_resource("card_styles")
            return CardStyleDTO(
                id=style.id,
                guid=str(style.guid),
                name=style.name,
                is_active=style.is_active,
            )

    def delete_card_style(self, style_id: int) -> None:
        with self._uow:
            deleted = self._uow.bank.delete_card_style(style_id)
            if not deleted:
                raise CardStyleNotFound(f"Card style {style_id} not found")
            self._uow.commit()
            self._cache_service.invalidate_by_resource("card_styles")

    def get_or_create_account(self, student_guid: UUID) -> UserBankAccountDTO:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                styles = self._uow.bank.get_all_card_styles(only_active=True)
                if not styles:
                    raise CardStyleNotFound("No active card styles available")
                default_style = styles[0]
                card_number = self._uow.bank.generate_unique_card_number()
                account = self._uow.bank.create_account(
                    student_guid=student_guid,
                    card_style_id=default_style.id,
                    card_number=card_number,
                )
                self._uow.commit()
            return self._account_to_dto(account)

    def update_user_card_style(self, student_guid: UUID, card_style_id: int) -> AccountOperationResponseDTO:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                raise BankAccountNotFound("Account not found")
            style = self._uow.bank.get_card_style_by_id(card_style_id)
            if not style or not style.is_active:
                raise CardStyleNotFound("Card style not found or not active")
            account = self._uow.bank.update_account_style(account.guid, card_style_id)
            self._uow.commit()
            self._invalidate_user_cache(student_guid)
            return AccountOperationResponseDTO(
                student_guid=str(student_guid),
                card_style_id=card_style_id,
                card_number=account.card_number,
                balance=account.balance,
            )

    # def get_account_info(self, student_guid: UUID) -> UserBankAccountDTO:
    #     with self._uow:
    #         account = self._uow.bank.get_account_by_student(student_guid)
    #         if not account:
    #             raise BankAccountNotFound("Account not found")
    #         return self._account_to_dto(account)

    def _account_to_dto(self, account) -> UserBankAccountDTO:
        return UserBankAccountDTO(
            guid=str(account.guid),
            student_guid=str(account.student_guid),
            card_style_id=account.card_style_id,
            card_number=account.card_number,
            balance=account.balance,
            created_at=account.created_at,
        )

    def get_transactions(self, student_guid: UUID, limit: int = 100) -> list[TransactionDTO]:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                return []
            txs = self._uow.bank.get_transactions_by_account(account.guid, limit)
            return [
                TransactionDTO(
                    guid=str(tx.guid),
                    type=tx.type.value,
                    amount=tx.amount,
                    description=tx.description,
                    status=tx.status.value,
                    created_at=tx.created_at,
                    additional_metadata=(json.loads(tx.additional_metadata) if tx.additional_metadata else None),
                )
                for tx in txs
            ]

    def get_transaction(self, transaction_guid: UUID, student_guid: UUID) -> TransactionDTO:
        with self._uow:
            tx = self._uow.bank.get_transaction_by_guid(transaction_guid)
            if not tx:
                raise TransactionNotFound(f"Transaction {transaction_guid} not found")
            account = self._uow.bank.get_account_by_guid(tx.account_guid)
            if not account or account.student_guid != student_guid:
                raise TransactionNotFound("Transaction not found or access denied")
            return TransactionDTO(
                guid=str(tx.guid),
                type=tx.type.value,
                amount=tx.amount,
                description=tx.description,
                status=tx.status.value,
                created_at=tx.created_at,
                additional_metadata=(json.loads(tx.additional_metadata) if tx.additional_metadata else None),
            )

    def deposit(
        self,
        student_guid: UUID,
        amount: int,
        description: str,
        additional_metadata: dict | None = None,
    ) -> TransactionDTO:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                styles = self._uow.bank.get_all_card_styles(only_active=True)
                if not styles:
                    raise CardStyleNotFound("No active card styles available")
                default_style = styles[0]
                card_number = self._uow.bank.generate_unique_card_number()
                account = self._uow.bank.create_account(
                    student_guid=student_guid,
                    card_style_id=default_style.id,
                    card_number=card_number,
                )
            account = self._uow.bank.update_account_balance(account.guid, amount)
            tx = self._uow.bank.create_transaction(
                account_guid=account.guid,
                _type=TransactionType.deposit,
                amount=amount,
                description=description,
                status=TransactionStatus.completed,
                additional_metadata=(json.dumps(additional_metadata) if additional_metadata else None),
            )
            self._uow.commit()
            self._invalidate_user_cache(student_guid)
            return TransactionDTO(
                guid=str(tx.guid),
                type=tx.type.value,
                amount=tx.amount,
                description=tx.description,
                status=tx.status.value,
                created_at=tx.created_at,
                additional_metadata=additional_metadata,
            )

    def create_withdrawal_request(self, student_guid: UUID, data: WithdrawalRequestCreateDTO) -> WithdrawalRequestDTO:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                raise BankAccountNotFound("Account not found")

            if data.amount < self.MIN_WITHDRAWAL_AMOUNT:
                raise WithdrawalAmountTooSmall(f"Minimum withdrawal amount is {self.MIN_WITHDRAWAL_AMOUNT}")

            if data.amount > account.balance:
                raise InsufficientBalance("Insufficient balance")

            pending_sum = self._uow.bank.get_sum_pending_withdrawal_requests(account.guid)
            available = account.balance - pending_sum

            if data.amount > available:
                raise InsufficientBalance(
                    f"Requested amount {data.amount} exceeds available balance after pending requests. Balance: {account.balance}, pending sum: {pending_sum}, available: {available}"
                )

            request = self._uow.bank.create_withdrawal_request(
                account_guid=account.guid,
                amount=data.amount,
                iban=data.iban,
                card_number=data.card_number,
                card_holder=data.card_holder,
                iin=data.iin,
            )
            self._uow.bank.create_transaction(
                account_guid=account.guid,
                _type=TransactionType.withdrawal,
                amount=data.amount,
                description="Withdrawal request created",
                status=TransactionStatus.pending,
                additional_metadata=json.dumps({"request_guid": str(request.guid)}),
            )
            self._uow.commit()
            self._invalidate_user_cache(student_guid)
            return self._request_to_dto(request)

    def get_withdrawal_requests(self, student_guid: UUID) -> list[WithdrawalRequestDTO]:
        with self._uow:
            account = self._uow.bank.get_account_by_student(student_guid)
            if not account:
                return []
            requests = self._uow.bank.get_withdrawal_requests_by_account(account.guid)
            return [self._request_to_dto(r) for r in requests]

    def get_withdrawal_request(self, request_guid: UUID, student_guid: UUID) -> WithdrawalRequestDTO:
        with self._uow:
            request = self._uow.bank.get_withdrawal_request_by_guid(request_guid)
            if not request:
                raise WithdrawalRequestNotFound(f"Request {request_guid} not found")
            account = self._uow.bank.get_account_by_guid(request.account_guid)
            if not account or account.student_guid != student_guid:
                raise WithdrawalRequestNotFound("Request not found or access denied")
            return self._request_to_dto(request)

    def get_pending_withdrawal_requests(self) -> list[WithdrawalRequestDTO]:
        with self._uow:
            requests = self._uow.bank.get_pending_withdrawal_requests()
            return [self._request_to_dto(r) for r in requests]

    def update_withdrawal_request_status(
        self, request_guid: UUID, data: WithdrawalRequestUpdateDTO
    ) -> WithdrawalRequestDTO:
        with self._uow:
            request = self._uow.bank.get_withdrawal_request_by_guid(request_guid)
            if not request:
                raise WithdrawalRequestNotFound(f"Request {request_guid} not found")

            if data.status == "approved":
                new_status = WithdrawalRequestStatus.approved
                account = self._uow.bank.get_account_by_guid(request.account_guid)
                if account and account.balance >= request.amount:
                    self._uow.bank.update_account_balance(account.guid, -request.amount)
                else:
                    raise InsufficientBalance("Insufficient balance")
            elif data.status == "rejected":
                new_status = WithdrawalRequestStatus.rejected
            else:
                raise InvalidWithdrawalStatus(f"Invalid status: {data.status}")

            updated = self._uow.bank.update_withdrawal_request_status(request_guid, new_status, data.comment)
            self._uow.commit()
            self._cache_service.invalidate_by_resource("withdrawal_requests")
            return self._request_to_dto(updated)

    def _request_to_dto(self, request) -> WithdrawalRequestDTO:
        return WithdrawalRequestDTO(
            guid=str(request.guid),
            account_guid=str(request.account_guid),
            amount=request.amount,
            iban=request.iban,
            card_number=request.card_number,
            card_holder=request.card_holder,
            iin=request.iin,
            status=request.status.value,
            admin_comment=request.admin_comment,
            created_at=request.created_at,
            processed_at=request.processed_at,
        )

    def _invalidate_user_cache(self, student_guid: UUID):
        self._cache_service.invalidate_by_resources(
            ["bank_account", "bank_transactions", "withdrawal_requests"],
            user_id=student_guid,
        )
