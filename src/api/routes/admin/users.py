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
