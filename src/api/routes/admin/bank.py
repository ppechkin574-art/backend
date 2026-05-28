from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import allow_only_admins, get_bank_service
from bank.dtos import (
    CardStyleCreateDTO,
    CardStyleDTO,
    CardStyleUpdateDTO,
    WithdrawalRequestDTO,
    WithdrawalRequestUpdateDTO,
)
from bank.exceptions import (
    CardStyleNotFound,
    InsufficientBalance,
    InvalidWithdrawalStatus,
    WithdrawalRequestNotFound,
)
from bank.service import BankService

router = APIRouter(
    prefix="/admin/bank",
    tags=["Admin - Bank"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("/styles", response_model=list[CardStyleDTO])
async def get_all_styles(
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.get_all_card_styles(only_active=False)


@router.post("/styles", response_model=CardStyleDTO)
async def create_style(
    data: CardStyleCreateDTO,
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.create_card_style(data)


@router.get("/styles/{style_id}", response_model=CardStyleDTO)
async def get_style(
    style_id: int,
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.get_card_style_by_id(style_id)
    except CardStyleNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/styles/{style_id}", response_model=CardStyleDTO)
async def update_style(
    style_id: int,
    data: CardStyleUpdateDTO,
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.update_card_style(style_id, data)
    except CardStyleNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/styles/{style_id}", status_code=204)
async def delete_style(
    style_id: int,
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        bank_service.delete_card_style(style_id)
    except CardStyleNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/withdrawals/pending", response_model=list[WithdrawalRequestDTO])
async def get_pending_withdrawals(
    bank_service: BankService = Depends(get_bank_service),
):
    return bank_service.get_pending_withdrawal_requests()


@router.patch("/withdrawals/{request_guid}", response_model=WithdrawalRequestDTO)
async def update_withdrawal_request(
    request_guid: UUID,
    data: WithdrawalRequestUpdateDTO,
    bank_service: BankService = Depends(get_bank_service),
):
    try:
        return bank_service.update_withdrawal_request_status(request_guid, data)
    except (
        WithdrawalRequestNotFound,
        InsufficientBalance,
        InvalidWithdrawalStatus,
    ) as e:
        raise HTTPException(status_code=400, detail=str(e))


class CreditDTO(BaseModel):
    """Manual coin credit. `reason` lands in the transaction's
    `description` so the audit trail is readable in withdrawal/bank
    reports without hunting through metadata JSON."""

    user_id: UUID
    amount: int = Field(..., ge=1, le=1_000_000)
    reason: str = Field(..., min_length=1, max_length=200)


class CreditResultDTO(BaseModel):
    user_id: UUID
    amount: int
    new_balance: int


@router.post("/credit", response_model=CreditResultDTO)
async def credit_coins(
    body: CreditDTO,
    bank_service: BankService = Depends(get_bank_service),
):
    """Manually credit coins to a user's bank balance. Auto-creates the
    bank account with the default card style if the user doesn't have
    one yet. Logged as a `deposit` transaction with source=admin_credit
    so it shows up in the user's transaction history with attribution."""
    bank_service.deposit(
        student_guid=body.user_id,
        amount=body.amount,
        description=body.reason,
        additional_metadata={
            "source": "admin_credit",
        },
    )
    # Re-read account to surface the updated balance to the operator.
    account = bank_service.get_or_create_account(body.user_id)
    return CreditResultDTO(
        user_id=body.user_id,
        amount=body.amount,
        new_balance=int(account.balance or 0),
    )
