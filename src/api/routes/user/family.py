from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import (
    get_family_service,
    get_user,
)
from auth.dtos.users import UserDTO
from quiz.services.family import FamilyService
from quiz.dtos.family import InviteRequest, RespondRequest
from quiz.exceptions import (
    InvitationNotFound,
    AlreadyInvited,
    CannotInviteSelf,
    InvalidAction,
)

router = APIRouter(prefix="/family", tags=["Family"])


@router.post("/invite", status_code=201)
async def send_invitation(
    request: InviteRequest,
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    if user.role not in ("parent", "child"):
        raise HTTPException(
            403, "Only users with parent or child role can send invitations"
        )
    try:
        return service.send_invitation(user, request.child_id)
    except CannotInviteSelf:
        raise HTTPException(400, "Cannot invite yourself")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except AlreadyInvited:
        raise HTTPException(409, "Invitation already pending or already connected")


# Список отправленных приглашений (инициатор)
@router.get("/invitations/sent")
async def get_sent_invitations(
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    return service.get_sent_invitations(user)


# Список полученных приглашений (приглашённая сторона)
@router.get("/invitations/received")
async def get_received_invitations(
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    return service.get_received_invitations(user)


# Ответ на приглашение (принимает/отклоняет приглашённая сторона)
@router.post("/respond")
async def respond_to_invitation(
    request: RespondRequest,
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    accept = request.action == "accept"
    try:
        return service.respond_to_invitation(user, request.invitation_id, accept)
    except InvitationNotFound:
        raise HTTPException(404, "Invitation not found")
    except InvalidAction:
        raise HTTPException(400, "Invitation already processed")


# Список подтверждённых детей – только для родителей
@router.get("/children")
async def get_children(
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    if "parent" not in user.roles:
        raise HTTPException(403, "Only parents can view children")
    return service.get_children(user)


# Список подтверждённых родителей – только для детей
@router.get("/parents")
async def get_parents(
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    if "child" not in user.roles:
        raise HTTPException(403, "Only children can view parents")
    return service.get_parents(user)


# Удаление ребёнка – только для родителей
@router.delete("/children/{child_id}")
async def remove_child(
    child_id: UUID,
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    if "parent" not in user.roles:
        raise HTTPException(403, "Only parents can remove children")
    try:
        return service.remove_child(user, child_id)
    except InvitationNotFound:
        raise HTTPException(404, "Child not found")


# Отмена приглашения (только инициатором)
@router.delete("/invitations/{invitation_id}")
async def cancel_invitation(
    invitation_id: int,
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    try:
        return service.cancel_invitation(user, invitation_id)
    except InvitationNotFound:
        raise HTTPException(404, "Invitation not found or cannot be cancelled")


@router.delete("/parent/{parent_id}")
async def remove_parent(
    parent_id: UUID,
    user: UserDTO = Depends(get_user),
    service: FamilyService = Depends(get_family_service),
):
    if "child" not in user.roles:
        raise HTTPException(403, "Only children can remove parents")
    try:
        return service.remove_parent(user, parent_id)
    except InvitationNotFound:
        raise HTTPException(404, "Parent not found")
