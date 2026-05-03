# В api/routes/user/users.py
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from api.dependencies import get_user, get_identity_provider_client_keycloak
from auth.dtos.users import UserDTO
from clients.identity_provider.client import IdentityProviderClientKeycloak
from clients.identity_provider.dtos import KeycloakUserQueryDTO

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/{user_id}")
async def get_user_by_id(
    user_id: UUID,
    current_user: UserDTO = Depends(get_user),
    idp: IdentityProviderClientKeycloak = Depends(
        get_identity_provider_client_keycloak
    ),
):
    # Доступно только авторизованным, возвращаем минимальную информацию
    try:
        keycloak_user = idp.get(KeycloakUserQueryDTO(id=user_id))
        roles = idp.get_roles(user_id)
        name = (
            keycloak_user.attributes.name[0]
            if keycloak_user.attributes and keycloak_user.attributes.name
            else ""
        )
        avatar = (
            keycloak_user.attributes.avatar[0]
            if keycloak_user.attributes and keycloak_user.attributes.avatar
            else None
        )
        return {
            "id": user_id,
            "name": name,
            "avatar": avatar,
            "role": (
                "parent"
                if "parent" in roles
                else ("child" if "child" in roles else "unknown")
            ),
        }
    except Exception:
        raise HTTPException(404, "User not found")
