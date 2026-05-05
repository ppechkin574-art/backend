import logging
from uuid import UUID
from typing import List
from sqlalchemy.orm import Session
from clients.identity_provider.dtos import KeycloakUserQueryDTO
from quiz.repositories.user_relationship import UserRelationshipRepository
from auth.dtos import UserDTO
from auth.exceptions import AuthUserNotFoundError
from clients.identity_provider.client import IdentityProviderClientKeycloak
from quiz.exceptions import (
    InvitationNotFound,
    AlreadyInvited,
    CannotInviteSelf,
    UserNotChild,
    InvalidAction,
)

logger = logging.getLogger(__name__)


class FamilyService:
    def __init__(self, session: Session, idp_client: IdentityProviderClientKeycloak):
        self._session = session
        self._repo = UserRelationshipRepository(session)
        self._idp = idp_client

    def _get_user_role(self, user_id: UUID) -> str:
        try:
            # Existence check — raises AuthUserNotFoundError on miss.
            self._idp.get(KeycloakUserQueryDTO(id=user_id))
            roles = self._idp.get_roles(user_id)
            if "parent" in roles:
                return "parent"
            elif "child" in roles:
                return "child"
            return "unknown"
        except Exception:
            raise AuthUserNotFoundError

    def _get_user_info(self, user_id: UUID) -> tuple[str, str | None]:
        """Возвращает (name, avatar)"""
        try:
            user = self._idp.get(KeycloakUserQueryDTO(id=user_id))
            name = (
                user.attributes.name[0]
                if user.attributes and user.attributes.name
                else ""
            )
            avatar = (
                user.attributes.avatar[0]
                if user.attributes and user.attributes.avatar
                else None
            )
            return name, avatar
        except Exception:
            return "Unknown", None

    def send_invitation(self, inviter: UserDTO, target_id: UUID) -> dict:
        if inviter.id == target_id:
            raise CannotInviteSelf("Cannot invite yourself")

        inviter_role = self._get_user_role(inviter.id)
        target_role = self._get_user_role(target_id)

        if inviter_role not in ("parent", "child") or target_role not in (
            "parent",
            "child",
        ):
            raise ValueError(
                "Only users with parent or child role can send/receive invitations"
            )
        if inviter_role == target_role:
            raise ValueError(
                f"Cannot invite user with same role: {inviter_role} to {target_role}"
            )

        if inviter_role == "parent" and target_role == "child":
            parent_id = inviter.id
            child_id = target_id
        else:
            parent_id = target_id
            child_id = inviter.id

        # Проверяем, нет ли уже подтверждённой связи
        confirmed = self._repo.get_confirmed_children(parent_id)
        if any(rel.child_id == child_id for rel in confirmed):
            raise AlreadyInvited("Already connected")

        # Проверяем существующую запись (любую, кроме confirmed/pending)
        existing = self._repo.get_relationship(parent_id, child_id)
        if existing and existing.status not in ("confirmed", "pending"):
            # Удаляем её, чтобы можно было создать новое приглашение
            self._repo.delete_relationship_by_parent_child(parent_id, child_id)
            self._session.flush()  # <-- ВАЖНО: принудительно применяем удаление

        # Проверяем, нет ли уже pending приглашения (после удаления)
        pending = self._repo.get_pending_invitation(parent_id, child_id)
        if pending:
            raise AlreadyInvited("Invitation already pending")

        # Создаём новое приглашение
        invitation = self._repo.create_invitation(inviter.id, parent_id, child_id)
        self._session.commit()
        return {"invitation_id": invitation.id, "status": "pending"}

    def respond_to_invitation(
        self, user: UserDTO, invitation_id: int, accept: bool
    ) -> dict:
        invitation = self._repo.get_invitation_for_invitee(invitation_id, user.id)
        if not invitation:
            raise InvitationNotFound("Invitation not found or already processed")
        if invitation.status != "pending":
            raise InvalidAction("Invitation already processed")
        new_status = "confirmed" if accept else "rejected"
        self._repo.update_status(invitation_id, new_status)
        self._session.commit()
        return {"invitation_id": invitation_id, "status": new_status}

    def get_sent_invitations(self, user: UserDTO) -> List[dict]:
        invitations = self._repo.get_sent_invitations(user.id, status="pending")
        result = []
        for inv in invitations:
            # target – противоположная сторона (не инициатор)
            target_id = inv.child_id if inv.parent_id == user.id else inv.parent_id
            name, avatar = self._get_user_info(target_id)
            result.append(
                {
                    "id": inv.id,
                    "target_id": target_id,
                    "target_name": name,
                    "target_avatar": avatar,
                    "created_at": inv.created_at,
                }
            )
        return result

    def get_received_invitations(self, user: UserDTO) -> List[dict]:
        invitations = self._repo.get_received_invitations(user.id, status="pending")
        result = []
        for inv in invitations:
            inviter_name, inviter_avatar = self._get_user_info(inv.inviter_id)
            result.append(
                {
                    "id": inv.id,
                    "inviter_id": inv.inviter_id,
                    "inviter_name": inviter_name,
                    "inviter_avatar": inviter_avatar,
                    "created_at": inv.created_at,
                }
            )
        return result

    def get_children(self, parent: UserDTO) -> List[dict]:
        relationships = self._repo.get_confirmed_children(parent.id)
        result = []
        for rel in relationships:
            name, avatar = self._get_user_info(rel.child_id)
            result.append(
                {
                    "user_id": rel.child_id,
                    "name": name,
                    "avatar": avatar,
                    "since": rel.updated_at,
                }
            )
        return result

    def get_parents(self, child: UserDTO) -> List[dict]:
        relationships = self._repo.get_confirmed_parents(child.id)
        result = []
        for rel in relationships:
            name, avatar = self._get_user_info(rel.parent_id)
            result.append(
                {
                    "user_id": rel.parent_id,
                    "name": name,
                    "avatar": avatar,
                    "since": rel.updated_at,
                }
            )
        return result

    def remove_child(self, parent: UserDTO, child_id: UUID) -> dict:
        deleted = self._repo.delete_relationship(parent.id, child_id)
        if not deleted:
            raise InvitationNotFound("Relationship not found")
        self._session.commit()
        return {"status": "removed"}

    def cancel_invitation(self, user: UserDTO, invitation_id: int) -> dict:
        invitation = self._repo.get_invitation_for_inviter(invitation_id, user.id)
        if not invitation:
            raise InvitationNotFound("Invitation not found or cannot be cancelled")
        deleted = self._repo.delete_pending_invitation_by_inviter(
            invitation_id, user.id
        )
        if not deleted:
            raise InvitationNotFound("Invitation not found or cannot be cancelled")
        self._session.commit()
        return {"status": "cancelled", "invitation_id": invitation_id}

    def remove_parent(self, child: UserDTO, parent_id: UUID) -> dict:
        """Удалить подтверждённого родителя у ребёнка."""
        deleted = self._repo.delete_relationship_by_child(child.id, parent_id)
        if not deleted:
            raise InvitationNotFound("Parent not found")
        self._session.commit()
        return {"status": "removed"}
