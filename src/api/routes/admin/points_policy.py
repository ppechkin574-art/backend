"""Admin CRUD for the points-awarding policy.

GET  /admin/points-policies             — list all four activity-type policies
GET  /admin/points-policies/{activity_type}  — get one
PUT  /admin/points-policies/{activity_type}  — update (partial: only provided fields change)

There is no POST / DELETE — the four rows are seeded by migration.
Gated by allow_only_admins.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import allow_only_admins, get_points_policy_service
from quiz.dtos.points_policy import PointsPolicyDTO, PointsPolicyUpdateDTO
from quiz.services.points_policy_service import PointsPolicyService

router = APIRouter(
    prefix="/admin/points-policies",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("", response_model=list[PointsPolicyDTO])
def list_policies(
    service: PointsPolicyService = Depends(get_points_policy_service),
):
    return service.list_all()


@router.get("/{activity_type}", response_model=PointsPolicyDTO)
def get_policy(
    activity_type: str,
    service: PointsPolicyService = Depends(get_points_policy_service),
):
    policy = service.get_one(activity_type)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return policy


@router.put("/{activity_type}", response_model=PointsPolicyDTO)
def update_policy(
    activity_type: str,
    body: PointsPolicyUpdateDTO,
    service: PointsPolicyService = Depends(get_points_policy_service),
):
    policy = service.update(activity_type, body)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return policy
