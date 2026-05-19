from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import allow_only_admins, get_admin_user_service
from auth.admin_service import AdminUserService
from auth.dtos.admin import (
    AdminUserCreateDTO,
    AdminUserCreateResponseDTO,
    AdminUserUpdateDTO,
)
from auth.dtos.users import UserDTO

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin - Users"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("", response_model=list[UserDTO])
async def get_users(
    role: str | None = None,
    search: str | None = None,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.get_users(role=role, search=search)


@router.post("", response_model=AdminUserCreateResponseDTO, status_code=201)
async def create_user(
    data: AdminUserCreateDTO,
    service: AdminUserService = Depends(get_admin_user_service),
):
    try:
        return service.create_user(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{user_id}", response_model=UserDTO)
async def get_user(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserDTO)
async def update_user(
    user_id: UUID,
    data: AdminUserUpdateDTO,
    service: AdminUserService = Depends(get_admin_user_service),
):
    return service.update_user(user_id, data)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    service.delete_user(user_id)
    return None


@router.post("/{user_id}/reset-subscription", response_model=UserDTO)
async def reset_subscription(
    user_id: UUID,
    service: AdminUserService = Depends(get_admin_user_service),
):
    """Forcibly rewind the user's subscription to FREE.

    Used to prepare demo accounts (e.g. Apple Reviewer) before
    submitting a build for App Store review — the reviewer needs
    to see "Купить подписку" rather than the cancel CTA, so any
    pre-existing PRO state has to be wiped from Keycloak attrs.
    The regular `cancel_subscription` endpoint is a soft-cancel
    and won't help here (it leaves plan=PRO until subscription_end).

    Admin-only (this whole router is `allow_only_admins`).
    """
    return service.reset_subscription(user_id)
