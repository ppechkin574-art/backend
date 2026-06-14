from sqlalchemy.orm import Session

from quiz.models.points_policy import PointsPolicy


class PointsPolicyRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_all(self) -> list[PointsPolicy]:
        return self._session.query(PointsPolicy).order_by(PointsPolicy.activity_type).all()

    def get_by_activity_type(self, activity_type: str) -> PointsPolicy | None:
        return self._session.get(PointsPolicy, activity_type)

    def update(self, activity_type: str, **kwargs) -> PointsPolicy | None:
        policy = self.get_by_activity_type(activity_type)
        if policy is None:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(policy, key, value)
        self._session.flush()
        return policy
