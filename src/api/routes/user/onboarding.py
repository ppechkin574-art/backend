"""Public onboarding endpoints consumed by the mobile app."""

from fastapi import APIRouter, Depends

from api.dependencies import get_onboarding_service, get_user
from auth.dtos import UserDTO
from onboarding.dtos import (
    OnboardingStoryPublicDTO,
    OnboardingViewDTO,
    OnboardingViewResponseDTO,
)
from onboarding.service import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/stories", response_model=list[OnboardingStoryPublicDTO])
def list_active_stories(
    service: OnboardingService = Depends(get_onboarding_service),
    user: UserDTO = Depends(get_user),
):
    """Returns active stories visible to this user. is_test stories only appear for test phones."""
    phone = str(user.phone) if user.phone else None
    return [OnboardingStoryPublicDTO.model_validate(s) for s in service.list_active(phone)]


@router.get("/stories/views", response_model=dict[int, int])
def get_user_views(
    service: OnboardingService = Depends(get_onboarding_service),
    user: UserDTO = Depends(get_user),
):
    """Returns {story_id: view_count} — how many times this user saw each story."""
    return service.get_user_views(user.id)


@router.post("/stories/{story_id}/view", response_model=OnboardingViewResponseDTO)
def record_view(
    story_id: int,
    body: OnboardingViewDTO,
    service: OnboardingService = Depends(get_onboarding_service),
    user: UserDTO = Depends(get_user),
):
    """Record that user viewed/skipped a story."""
    body.story_id = story_id
    result = service.record_view(user.id, body)
    service.repo.db.commit()
    return result
