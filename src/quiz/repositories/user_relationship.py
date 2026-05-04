from datetime import datetime

from sqlalchemy.orm import Session
from quiz.models.user_relationship import UserRelationship
from uuid import UUID
from typing import List, Optional


class UserRelationshipRepository:
    def __init__(self, session: Session):
        self._session = session

    def create_invitation(
        self, inviter_id: UUID, parent_id: UUID, child_id: UUID
    ) -> UserRelationship:
        rel = UserRelationship(
            inviter_id=inviter_id,
            parent_id=parent_id,
            child_id=child_id,
            status="pending",
        )
        self._session.add(rel)
        self._session.flush()
        return rel

    def get_invitation(self, invitation_id: int) -> Optional[UserRelationship]:
        return self._session.query(UserRelationship).filter_by(id=invitation_id).first()

    def get_pending_invitation(
        self, parent_id: UUID, child_id: UUID
    ) -> Optional[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter_by(parent_id=parent_id, child_id=child_id, status="pending")
            .first()
        )

    def get_sent_invitations(
        self, user_id: UUID, status: Optional[str] = None
    ) -> List[UserRelationship]:
        q = self._session.query(UserRelationship).filter_by(inviter_id=user_id)
        if status:
            q = q.filter_by(status=status)
        return q.all()

    def get_received_invitations(
        self, user_id: UUID, status: Optional[str] = None
    ) -> List[UserRelationship]:
        q = self._session.query(UserRelationship).filter(
            (UserRelationship.parent_id == user_id)
            | (UserRelationship.child_id == user_id),
            UserRelationship.inviter_id != user_id,
        )
        if status:
            q = q.filter_by(status=status)
        return q.all()

    def get_confirmed_children(self, parent_id: UUID) -> List[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter_by(parent_id=parent_id, status="confirmed")
            .all()
        )

    def get_confirmed_parents(self, child_id: UUID) -> List[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter_by(child_id=child_id, status="confirmed")
            .all()
        )

    def update_status(
        self, invitation_id: int, new_status: str
    ) -> Optional[UserRelationship]:
        rel = self.get_invitation(invitation_id)
        if rel:
            rel.status = new_status
            rel.updated_at = datetime.utcnow()
            self._session.flush()
        return rel

    def delete_relationship(self, parent_id: UUID, child_id: UUID) -> bool:
        rel = (
            self._session.query(UserRelationship)
            .filter_by(parent_id=parent_id, child_id=child_id)
            .first()
        )
        if rel:
            self._session.delete(rel)
            return True
        return False

    def delete_pending_invitation(self, invitation_id: int, parent_id: UUID) -> bool:
        """Удалить приглашение, если оно принадлежит родителю и имеет статус pending"""
        rel = (
            self._session.query(UserRelationship)
            .filter_by(id=invitation_id, parent_id=parent_id, status="pending")
            .first()
        )
        if rel:
            self._session.delete(rel)
            return True
        return False

    def get_invitation_for_invitee(
        self, invitation_id: int, user_id: UUID
    ) -> Optional[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter(
                UserRelationship.id == invitation_id,
                UserRelationship.status == "pending",
                (UserRelationship.parent_id == user_id)
                | (UserRelationship.child_id == user_id),
                UserRelationship.inviter_id != user_id,
            )
            .first()
        )

    def get_invitation_for_inviter(
        self, invitation_id: int, inviter_id: UUID
    ) -> Optional[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter_by(id=invitation_id, inviter_id=inviter_id, status="pending")
            .first()
        )

    def delete_pending_invitation_by_inviter(
        self, invitation_id: int, inviter_id: UUID
    ) -> bool:
        rel = (
            self._session.query(UserRelationship)
            .filter_by(id=invitation_id, inviter_id=inviter_id, status="pending")
            .first()
        )
        if rel:
            self._session.delete(rel)
            return True
        return False

    def get_relationship(
        self, parent_id: UUID, child_id: UUID
    ) -> Optional[UserRelationship]:
        return (
            self._session.query(UserRelationship)
            .filter_by(parent_id=parent_id, child_id=child_id)
            .first()
        )

    def delete_relationship_by_parent_child(
        self, parent_id: UUID, child_id: UUID
    ) -> bool:
        rel = self.get_relationship(parent_id, child_id)
        if rel:
            self._session.delete(rel)
            return True
        return False

    def delete_relationship_by_child(self, child_id: UUID, parent_id: UUID) -> bool:
        """Удалить подтверждённую связь, где указаны child_id и parent_id."""
        rel = (
            self._session.query(UserRelationship)
            .filter_by(child_id=child_id, parent_id=parent_id, status="confirmed")
            .first()
        )
        if rel:
            self._session.delete(rel)
            return True
        return False
