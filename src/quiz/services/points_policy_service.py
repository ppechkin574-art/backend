from sqlalchemy.orm import Session

from quiz.dtos.points_policy import PointsPolicyDTO, PointsPolicyUpdateDTO
from quiz.models.points_policy import PointsPolicy
from quiz.repositories.points_policy import PointsPolicyRepository


class PointsPolicyService:
    def __init__(self, session: Session):
        self._repo = PointsPolicyRepository(session)
        self._session = session

    def list_all(self) -> list[PointsPolicyDTO]:
        policies = self._repo.get_all()
        return [PointsPolicyDTO.model_validate(p) for p in policies]

    def get_one(self, activity_type: str) -> PointsPolicyDTO | None:
        policy = self._repo.get_by_activity_type(activity_type)
        if policy is None:
            return None
        return PointsPolicyDTO.model_validate(policy)

    def update(self, activity_type: str, data: PointsPolicyUpdateDTO) -> PointsPolicyDTO | None:
        fields = data.model_dump(exclude_none=True)
        policy = self._repo.update(activity_type, **fields)
        if policy is None:
            return None
        self._session.commit()
        return PointsPolicyDTO.model_validate(policy)
