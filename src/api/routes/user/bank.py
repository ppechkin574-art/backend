from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_bank_service, get_user
from auth.dtos.users import UserDTO
from bank.dtos import (
    AccountOperationResponseDTO,
    CardStyleDTO,
    TransactionDTO,
    UpdateCardStyleRequestDTO,
    UserBankAccountDTO,
    WithdrawalRequestCreateDTO,
    WithdrawalRequestDTO,
)
from bank.exceptions import (
    BankAccountNotFound,
    CardStyleNotFound,
    InsufficientBalance,
    TransactionNotFound,
    WithdrawalAmountTooSmall,
    WithdrawalRequestNotFound,
)
from bank.service import BankService

router = APIRouter(
    prefix="/user/bank",
    tags=["User - Bank"],
    dependencies=[Depends(get_user)],
)


@router.get("/card-styles", response_model=list[CardStyleDTO])
async def get_card_styles(
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.get_all_card_styles(only_active=True)


@router.get("/account", response_model=UserBankAccountDTO)
async def get_account(
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.get_or_create_account(user.id)
    except CardStyleNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/account/card-styles", response_model=AccountOperationResponseDTO)
async def update_card_style(
    data: UpdateCardStyleRequestDTO,
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.update_user_card_style(user.id, data.card_style_id)
    except (BankAccountNotFound, CardStyleNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/transactions", response_model=list[TransactionDTO])
async def get_transactions(
    limit: int = Query(100, ge=1, le=500),
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.get_transactions(user.id, limit)


@router.get("/transactions/{transaction_guid}", response_model=TransactionDTO)
async def get_transaction(
    transaction_guid: UUID,
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.get_transaction(transaction_guid, user.id)
    except TransactionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/withdrawals", response_model=WithdrawalRequestDTO)
async def create_withdrawal_request(
    data: WithdrawalRequestCreateDTO,
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.create_withdrawal_request(user.id, data)
    except (
        BankAccountNotFound,
        WithdrawalAmountTooSmall,
        InsufficientBalance,
    ) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/withdrawals", response_model=list[WithdrawalRequestDTO])
async def get_withdrawal_requests(
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.get_withdrawal_requests(user.id)


@router.get("/withdrawals/{request_guid}", response_model=WithdrawalRequestDTO)
async def get_withdrawal_request(
    request_guid: UUID,
    user: UserDTO = Depends(get_user),
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.get_withdrawal_request(request_guid, user.id)
    except WithdrawalRequestNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
