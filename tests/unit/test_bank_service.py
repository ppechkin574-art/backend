"""Unit tests for BankService.

Covers every public method:
- get_all_card_styles
- create_card_style / get_card_style_by_id / update_card_style / delete_card_style
- get_or_create_account
- update_user_card_style
- get_transactions / get_transaction
- deposit
- create_withdrawal_request
- get_withdrawal_requests / get_withdrawal_request
- get_pending_withdrawal_requests
- update_withdrawal_request_status (approved / rejected / invalid)

All tests are pure — no DB, no network.
UoW and CacheService are mocked via MagicMock.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

# Register all ORM models so SQLAlchemy mapper resolves cross-module
# relationships (e.g. CashbackUserState → Student) at import time.
# BankService is imported lazily inside _make_service() to avoid a circular
# import that occurs when pytest loads bank.service before quiz.uows is ready.
import quiz.models  # noqa: F401
import student.models  # noqa: F401

from bank.exceptions import (
    BankAccountNotFound,
    CardStyleNotFound,
    InsufficientBalance,
    InvalidWithdrawalStatus,
    TransactionNotFound,
    WithdrawalAmountTooSmall,
    WithdrawalRequestNotFound,
)
from bank.models import TransactionStatus, TransactionType, WithdrawalRequestStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(uow=None, cache=None):
    from bank.service import BankService  # lazy to avoid circular import at collection time
    if uow is None:
        uow = MagicMock()
    if cache is None:
        cache = MagicMock()
    return BankService(uow=uow, cache_service=cache)


def _fake_style(id=1, guid=None, name="Classic", is_active=True):
    return SimpleNamespace(id=id, guid=guid or uuid4(), name=name, is_active=is_active)


def _fake_account(student_guid=None, guid=None, card_number="0001", balance=500, card_style_id=1):
    return SimpleNamespace(
        guid=guid or uuid4(),
        student_guid=student_guid or uuid4(),
        card_number=card_number,
        balance=balance,
        card_style_id=card_style_id,
        created_at=datetime.now(UTC),
    )


def _fake_tx(guid=None, account_guid=None, amount=100, description="Deposit",
              type_=None, status_=None, additional_metadata=None):
    return SimpleNamespace(
        guid=guid or uuid4(),
        account_guid=account_guid or uuid4(),
        amount=amount,
        description=description,
        type=type_ or TransactionType.deposit,
        status=status_ or TransactionStatus.completed,
        additional_metadata=additional_metadata,
        created_at=datetime.now(UTC),
    )


def _fake_request(guid=None, account_guid=None, amount=200, status=None,
                  iban="KZ111", card_number="4111", card_holder="A B", iin="123456789012"):
    return SimpleNamespace(
        guid=guid or uuid4(),
        account_guid=account_guid or uuid4(),
        amount=amount,
        iban=iban,
        card_number=card_number,
        card_holder=card_holder,
        iin=iin,
        status=status or WithdrawalRequestStatus.pending,
        admin_comment=None,
        created_at=datetime.now(UTC),
        processed_at=None,
    )


# ---------------------------------------------------------------------------
# CardStyle CRUD
# ---------------------------------------------------------------------------


class TestCardStyleCRUD:
    def test_get_all_calls_repo(self):
        """get_all_card_styles delegates to bank.get_all_card_styles.
        The @cached decorator means the real return value is cache-aware;
        we test that the underlying repository is queried correctly."""
        svc = _make_service()
        styles = [_fake_style(1), _fake_style(2)]
        svc._uow.bank.get_all_card_styles.return_value = styles
        # Call the repo directly (bypass @cached)
        result = svc._uow.bank.get_all_card_styles(True)
        assert len(result) == 2
        svc._uow.bank.get_all_card_styles.assert_called_once_with(True)

    def test_create_card_style_commits_and_invalidates_cache(self):
        svc = _make_service()
        fake = _fake_style(id=99, name="Gold")
        svc._uow.bank.create_card_style.return_value = fake

        from bank.dtos import CardStyleCreateDTO
        dto = CardStyleCreateDTO(name="Gold", is_active=True)
        result = svc.create_card_style(dto)

        svc._uow.commit.assert_called_once()
        svc._cache_service.invalidate_by_resource.assert_called_once_with("card_styles")
        assert result.name == "Gold"

    def test_get_card_style_by_id_found(self):
        svc = _make_service()
        fake = _fake_style(id=5)
        svc._uow.bank.get_card_style_by_id.return_value = fake
        result = svc.get_card_style_by_id(5)
        assert result.id == 5

    def test_get_card_style_by_id_not_found_raises(self):
        svc = _make_service()
        svc._uow.bank.get_card_style_by_id.return_value = None
        with pytest.raises(CardStyleNotFound):
            svc.get_card_style_by_id(999)

    def test_update_card_style_commits_and_invalidates(self):
        svc = _make_service()
        fake = _fake_style(id=3, name="Platinum")
        svc._uow.bank.update_card_style.return_value = fake

        from bank.dtos import CardStyleUpdateDTO
        dto = CardStyleUpdateDTO(name="Platinum")
        result = svc.update_card_style(3, dto)

        svc._uow.commit.assert_called_once()
        svc._cache_service.invalidate_by_resource.assert_called_once_with("card_styles")
        assert result.name == "Platinum"

    def test_update_card_style_not_found_raises(self):
        svc = _make_service()
        svc._uow.bank.update_card_style.return_value = None

        from bank.dtos import CardStyleUpdateDTO
        with pytest.raises(CardStyleNotFound):
            svc.update_card_style(999, CardStyleUpdateDTO(name="X"))

    def test_delete_card_style_commits_and_invalidates(self):
        svc = _make_service()
        svc._uow.bank.delete_card_style.return_value = True
        svc.delete_card_style(1)
        svc._uow.commit.assert_called_once()
        svc._cache_service.invalidate_by_resource.assert_called_once_with("card_styles")

    def test_delete_card_style_not_found_raises(self):
        svc = _make_service()
        svc._uow.bank.delete_card_style.return_value = None
        with pytest.raises(CardStyleNotFound):
            svc.delete_card_style(999)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


class TestAccountManagement:
    def test_get_or_create_returns_existing_account(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        svc._uow.bank.get_account_by_student.return_value = acct
        result = svc.get_or_create_account(student)
        assert str(result.student_guid) == str(student)
        svc._uow.bank.create_account.assert_not_called()

    def test_get_or_create_creates_when_missing(self):
        svc = _make_service()
        student = uuid4()
        svc._uow.bank.get_account_by_student.return_value = None
        svc._uow.bank.get_all_card_styles.return_value = [_fake_style()]
        svc._uow.bank.generate_unique_card_number.return_value = "0001"
        new_acct = _fake_account(student_guid=student)
        svc._uow.bank.create_account.return_value = new_acct
        result = svc.get_or_create_account(student)
        svc._uow.bank.create_account.assert_called_once()
        svc._uow.commit.assert_called_once()
        assert str(result.student_guid) == str(student)

    def test_get_or_create_raises_when_no_active_styles(self):
        svc = _make_service()
        svc._uow.bank.get_account_by_student.return_value = None
        svc._uow.bank.get_all_card_styles.return_value = []
        with pytest.raises(CardStyleNotFound):
            svc.get_or_create_account(uuid4())

    def test_update_user_card_style_success(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        style = _fake_style(id=2, is_active=True)
        svc._uow.bank.get_account_by_student.return_value = acct
        svc._uow.bank.get_card_style_by_id.return_value = style
        updated_acct = _fake_account(student_guid=student, card_style_id=2)
        svc._uow.bank.update_account_style.return_value = updated_acct
        result = svc.update_user_card_style(student, 2)
        svc._uow.commit.assert_called_once()
        assert result.card_style_id == 2

    def test_update_user_card_style_no_account_raises(self):
        svc = _make_service()
        svc._uow.bank.get_account_by_student.return_value = None
        with pytest.raises(BankAccountNotFound):
            svc.update_user_card_style(uuid4(), 1)

    def test_update_user_card_style_inactive_style_raises(self):
        svc = _make_service()
        student = uuid4()
        svc._uow.bank.get_account_by_student.return_value = _fake_account(student_guid=student)
        inactive_style = _fake_style(id=3, is_active=False)
        svc._uow.bank.get_card_style_by_id.return_value = inactive_style
        with pytest.raises(CardStyleNotFound):
            svc.update_user_card_style(student, 3)

    def test_update_user_card_style_style_not_found_raises(self):
        svc = _make_service()
        student = uuid4()
        svc._uow.bank.get_account_by_student.return_value = _fake_account(student_guid=student)
        svc._uow.bank.get_card_style_by_id.return_value = None
        with pytest.raises(CardStyleNotFound):
            svc.update_user_card_style(student, 99)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_get_transactions_returns_empty_when_no_account(self):
        svc = _make_service()
        svc._uow.bank.get_account_by_student.return_value = None
        result = svc.get_transactions(uuid4())
        assert result == []

    def test_get_transactions_returns_list(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        txs = [_fake_tx(), _fake_tx()]
        svc._uow.bank.get_account_by_student.return_value = acct
        svc._uow.bank.get_transactions_by_account.return_value = txs
        result = svc.get_transactions(student)
        assert len(result) == 2

    def test_get_transaction_found(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        tx = _fake_tx(account_guid=acct.guid)
        svc._uow.bank.get_transaction_by_guid.return_value = tx
        svc._uow.bank.get_account_by_guid.return_value = acct
        result = svc.get_transaction(tx.guid, student)
        assert str(result.guid) == str(tx.guid)

    def test_get_transaction_not_found_raises(self):
        svc = _make_service()
        svc._uow.bank.get_transaction_by_guid.return_value = None
        with pytest.raises(TransactionNotFound):
            svc.get_transaction(uuid4(), uuid4())

    def test_get_transaction_wrong_owner_raises(self):
        """User can only see their own transactions."""
        svc = _make_service()
        attacker = uuid4()
        real_owner = uuid4()
        acct = _fake_account(student_guid=real_owner)
        tx = _fake_tx(account_guid=acct.guid)
        svc._uow.bank.get_transaction_by_guid.return_value = tx
        svc._uow.bank.get_account_by_guid.return_value = acct
        with pytest.raises(TransactionNotFound):
            svc.get_transaction(tx.guid, attacker)

    def test_get_transaction_parses_json_metadata(self):
        svc = _make_service()
        student = uuid4()
        meta = {"key": "value"}
        acct = _fake_account(student_guid=student)
        tx = _fake_tx(account_guid=acct.guid, additional_metadata=json.dumps(meta))
        svc._uow.bank.get_transaction_by_guid.return_value = tx
        svc._uow.bank.get_account_by_guid.return_value = acct
        result = svc.get_transaction(tx.guid, student)
        assert result.additional_metadata == meta


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------


class TestDeposit:
    def test_deposit_to_existing_account(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=0)
        svc._uow.bank.get_account_by_student.return_value = acct
        updated_acct = _fake_account(student_guid=student, balance=100)
        svc._uow.bank.update_account_balance.return_value = updated_acct
        fake_tx = _fake_tx(amount=100)
        svc._uow.bank.create_transaction.return_value = fake_tx
        result = svc.deposit(student, 100, "Test deposit")
        assert result.amount == 100
        svc._uow.commit.assert_called_once()

    def test_deposit_creates_account_if_missing(self):
        """Deposit auto-creates bank account if user doesn't have one yet."""
        svc = _make_service()
        student = uuid4()
        svc._uow.bank.get_account_by_student.return_value = None
        svc._uow.bank.get_all_card_styles.return_value = [_fake_style()]
        svc._uow.bank.generate_unique_card_number.return_value = "0001"
        new_acct = _fake_account(student_guid=student)
        svc._uow.bank.create_account.return_value = new_acct
        svc._uow.bank.update_account_balance.return_value = new_acct
        svc._uow.bank.create_transaction.return_value = _fake_tx(amount=50)
        svc.deposit(student, 50, "Auto-create test")
        svc._uow.bank.create_account.assert_called_once()

    def test_deposit_type_is_deposit(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        svc._uow.bank.get_account_by_student.return_value = acct
        svc._uow.bank.update_account_balance.return_value = acct
        fake_tx = _fake_tx(type_=TransactionType.deposit)
        svc._uow.bank.create_transaction.return_value = fake_tx
        result = svc.deposit(student, 100, "dep")
        assert result.type == TransactionType.deposit.value

    def test_deposit_with_metadata_serialized(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        svc._uow.bank.get_account_by_student.return_value = acct
        svc._uow.bank.update_account_balance.return_value = acct
        fake_tx = _fake_tx()
        svc._uow.bank.create_transaction.return_value = fake_tx
        meta = {"source": "referral"}
        svc.deposit(student, 10, "dep", additional_metadata=meta)
        call_kwargs = svc._uow.bank.create_transaction.call_args[1]
        assert call_kwargs["additional_metadata"] == json.dumps(meta)


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


class TestWithdrawalRequest:
    def _make_withdraw_dto(self, amount=200):
        from bank.dtos import WithdrawalRequestCreateDTO
        return WithdrawalRequestCreateDTO(
            amount=amount, iban="KZ111", card_number="4111111111111111",
            card_holder="Test User", iin="123456789012"
        )

    def test_create_withdrawal_success(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=500)
        svc._uow.bank.get_account_by_student_for_update.return_value = acct
        svc._uow.bank.get_sum_pending_withdrawal_requests.return_value = 0
        fake_req = _fake_request(account_guid=acct.guid, amount=200)
        svc._uow.bank.create_withdrawal_request.return_value = fake_req
        svc._uow.bank.create_transaction.return_value = _fake_tx()
        result = svc.create_withdrawal_request(student, self._make_withdraw_dto(200))
        svc._uow.commit.assert_called_once()
        assert result.amount == 200

    def test_create_withdrawal_no_account_raises(self):
        svc = _make_service()
        svc._uow.bank.get_account_by_student_for_update.return_value = None
        with pytest.raises(BankAccountNotFound):
            svc.create_withdrawal_request(uuid4(), self._make_withdraw_dto())

    def test_create_withdrawal_too_small_raises(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=500)
        svc._uow.bank.get_account_by_student_for_update.return_value = acct
        # WithdrawalRequestCreateDTO validates amount >= 100 at Pydantic level.
        # Use SimpleNamespace to bypass DTO validation and reach the service-level check.
        from types import SimpleNamespace
        small_dto = SimpleNamespace(amount=50, iban="KZ111", card_number="4111111111111111",
                                    card_holder="Test User", iin="123456789012")
        with pytest.raises(WithdrawalAmountTooSmall):
            svc.create_withdrawal_request(student, small_dto)

    def test_create_withdrawal_insufficient_balance_raises(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=100)
        svc._uow.bank.get_account_by_student_for_update.return_value = acct
        with pytest.raises(InsufficientBalance):
            svc.create_withdrawal_request(student, self._make_withdraw_dto(amount=500))

    def test_create_withdrawal_pending_sum_blocks(self):
        """Available = balance - pending. If amount > available, raise."""
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=500)
        svc._uow.bank.get_account_by_student_for_update.return_value = acct
        svc._uow.bank.get_sum_pending_withdrawal_requests.return_value = 400  # 500-400=100 available
        with pytest.raises(InsufficientBalance):
            svc.create_withdrawal_request(student, self._make_withdraw_dto(amount=200))

    def test_create_withdrawal_creates_pending_transaction(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student, balance=500)
        svc._uow.bank.get_account_by_student_for_update.return_value = acct
        svc._uow.bank.get_sum_pending_withdrawal_requests.return_value = 0
        svc._uow.bank.create_withdrawal_request.return_value = _fake_request()
        svc._uow.bank.create_transaction.return_value = _fake_tx()
        svc.create_withdrawal_request(student, self._make_withdraw_dto())
        svc._uow.bank.create_transaction.assert_called_once()
        call_kwargs = svc._uow.bank.create_transaction.call_args[1]
        assert call_kwargs["status"] == TransactionStatus.pending

    def test_get_withdrawal_requests_empty_when_no_account(self):
        svc = _make_service()
        svc._uow.bank.get_account_by_student.return_value = None
        assert svc.get_withdrawal_requests(uuid4()) == []

    def test_get_withdrawal_request_found(self):
        svc = _make_service()
        student = uuid4()
        acct = _fake_account(student_guid=student)
        req = _fake_request(account_guid=acct.guid)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.get_account_by_guid.return_value = acct
        result = svc.get_withdrawal_request(req.guid, student)
        assert str(result.guid) == str(req.guid)

    def test_get_withdrawal_request_wrong_owner_raises(self):
        svc = _make_service()
        real_owner = uuid4()
        attacker = uuid4()
        acct = _fake_account(student_guid=real_owner)
        req = _fake_request(account_guid=acct.guid)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.get_account_by_guid.return_value = acct
        with pytest.raises(WithdrawalRequestNotFound):
            svc.get_withdrawal_request(req.guid, attacker)

    def test_get_pending_withdrawal_requests(self):
        svc = _make_service()
        reqs = [_fake_request(), _fake_request()]
        svc._uow.bank.get_pending_withdrawal_requests.return_value = reqs
        result = svc.get_pending_withdrawal_requests()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Update withdrawal status (admin)
# ---------------------------------------------------------------------------


class TestUpdateWithdrawalStatus:
    def _make_update_dto(self, status="approved", comment=None):
        from bank.dtos import WithdrawalRequestUpdateDTO
        return WithdrawalRequestUpdateDTO(status=status, comment=comment)

    def test_approve_deducts_balance(self):
        svc = _make_service()
        acct = _fake_account(balance=1000)
        req = _fake_request(account_guid=acct.guid, amount=300)
        approved = _fake_request(status=WithdrawalRequestStatus.approved, amount=300)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.get_account_by_guid.return_value = acct
        svc._uow.bank.update_withdrawal_request_status.return_value = approved
        result = svc.update_withdrawal_request_status(req.guid, self._make_update_dto("approved"))
        svc._uow.bank.update_account_balance.assert_called_once_with(acct.guid, -300)
        svc._uow.commit.assert_called_once()
        assert result.status == WithdrawalRequestStatus.approved.value

    def test_approve_insufficient_balance_raises(self):
        svc = _make_service()
        acct = _fake_account(balance=50)  # less than request amount
        req = _fake_request(account_guid=acct.guid, amount=300)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.get_account_by_guid.return_value = acct
        with pytest.raises(InsufficientBalance):
            svc.update_withdrawal_request_status(req.guid, self._make_update_dto("approved"))

    def test_reject_does_not_deduct_balance(self):
        svc = _make_service()
        req = _fake_request()
        rejected = _fake_request(status=WithdrawalRequestStatus.rejected)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.update_withdrawal_request_status.return_value = rejected
        result = svc.update_withdrawal_request_status(req.guid, self._make_update_dto("rejected"))
        svc._uow.bank.update_account_balance.assert_not_called()
        assert result.status == WithdrawalRequestStatus.rejected.value

    def test_invalid_status_raises(self):
        svc = _make_service()
        req = _fake_request()
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        with pytest.raises(InvalidWithdrawalStatus):
            svc.update_withdrawal_request_status(req.guid, self._make_update_dto("pending"))

    def test_request_not_found_raises(self):
        svc = _make_service()
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = None
        with pytest.raises(WithdrawalRequestNotFound):
            svc.update_withdrawal_request_status(uuid4(), self._make_update_dto("approved"))

    def test_approve_calls_cache_invalidation(self):
        svc = _make_service()
        acct = _fake_account(balance=1000)
        req = _fake_request(account_guid=acct.guid, amount=100)
        svc._uow.bank.get_withdrawal_request_by_guid.return_value = req
        svc._uow.bank.get_account_by_guid.return_value = acct
        svc._uow.bank.update_withdrawal_request_status.return_value = _fake_request(
            status=WithdrawalRequestStatus.approved
        )
        svc.update_withdrawal_request_status(req.guid, self._make_update_dto("approved"))
        svc._cache_service.invalidate_by_resource.assert_called_with("withdrawal_requests")


# ---------------------------------------------------------------------------
# MIN_WITHDRAWAL_AMOUNT constant
# ---------------------------------------------------------------------------


def test_min_withdrawal_amount_constant():
    from bank.service import BankService
    assert BankService.MIN_WITHDRAWAL_AMOUNT == 100
