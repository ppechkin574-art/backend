from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

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
