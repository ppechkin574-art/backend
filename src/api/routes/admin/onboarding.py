"""Admin CRUD for onboarding stories and image uploads."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from api.dependencies import (
    allow_read_or_admin_write,
    get_file_service,
    get_identity_provider_client_keycloak,
    get_onboarding_service,
)
from clients.identity_provider.client import IdentityProviderClientKeycloak
from onboarding.dtos import (
    OnboardingStepDTO,
    OnboardingStoryCreateDTO,
    OnboardingStoryDTO,
    OnboardingStoryUpdateDTO,
    ResetViewsRequestDTO,
    ResetViewsResponseDTO,
    StoryStatsDTO,
)
from onboarding.service import OnboardingService
from utils.file_service import FileService

router = APIRouter(
    prefix="/admin/onboarding",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


def _with_fresh_urls(story: OnboardingStoryDTO, fs: FileService) -> OnboardingStoryDTO:
    """Replace mascot_image_url with a fresh presigned URL (filename or expired URL → new link)."""
    for step in story.steps:
        if step.mascot_image_url:
            refreshed = fs.get_mascot_image_url(step.mascot_image_url)
            if refreshed:
                step.mascot_image_url = refreshed
    return story


# ── Stories ──────────────────────────────────────────────────────────────────

@router.get("/stories", response_model=list[OnboardingStoryDTO])
def list_stories(
    service: OnboardingService = Depends(get_onboarding_service),
    fs: FileService = Depends(get_file_service),
):
    return [_with_fresh_urls(OnboardingStoryDTO.model_validate(s), fs) for s in service.list_all()]


@router.post("/stories", response_model=OnboardingStoryDTO, status_code=201)
def create_story(
    body: OnboardingStoryCreateDTO,
    service: OnboardingService = Depends(get_onboarding_service),
    fs: FileService = Depends(get_file_service),
):
    story = service.create_story(body)
    service.repo.db.commit()
    return _with_fresh_urls(OnboardingStoryDTO.model_validate(service.get_story(story.id)), fs)


@router.get("/stories/{story_id}", response_model=OnboardingStoryDTO)
def get_story(
    story_id: int,
    service: OnboardingService = Depends(get_onboarding_service),
    fs: FileService = Depends(get_file_service),
):
    return _with_fresh_urls(OnboardingStoryDTO.model_validate(service.get_story(story_id)), fs)


@router.patch("/stories/{story_id}", response_model=OnboardingStoryDTO)
def update_story(
    story_id: int,
    body: OnboardingStoryUpdateDTO,
    service: OnboardingService = Depends(get_onboarding_service),
    fs: FileService = Depends(get_file_service),
):
    story = service.update_story(story_id, body)
    service.repo.db.commit()
    return _with_fresh_urls(OnboardingStoryDTO.model_validate(service.get_story(story.id)), fs)


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(
    story_id: int,
    service: OnboardingService = Depends(get_onboarding_service),
    fs: FileService = Depends(get_file_service),
):
    story = service.get_story(story_id)
    mascot_filenames = [s.mascot_image_url for s in story.steps if s.mascot_image_url]
    service.delete_story(story_id)
    service.repo.db.commit()
    for fname in mascot_filenames:
        fs.delete_mascot_image(fname)


# ── Stats & re-show ──────────────────────────────────────────────────────────

@router.get("/stories/{story_id}/stats", response_model=StoryStatsDTO)
def get_story_stats(
    story_id: int,
    service: OnboardingService = Depends(get_onboarding_service),
):
    return service.get_story_stats(story_id)


@router.post("/stories/{story_id}/reset-views", response_model=ResetViewsResponseDTO)
def reset_views(
    story_id: int,
    body: ResetViewsRequestDTO,
    service: OnboardingService = Depends(get_onboarding_service),
    identity_provider: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    user_id: UUID | None = None
    if body.mode == "user":
        if not body.user_phone:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="user_phone обязателен для режима user",
            )
        user_data = identity_provider._find_user_by_phone(body.user_phone)
        if user_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Пользователь с номером {body.user_phone} не найден",
            )
        user_id = UUID(user_data["id"])
    result = service.reset_views(story_id, body, user_id=user_id)
    service.repo.db.commit()
    return result


# ── Image upload ─────────────────────────────────────────────────────────────

@router.post("/upload-image")
async def upload_mascot_image(
    file: UploadFile = File(...),
    file_service: FileService = Depends(get_file_service),
):
    """Upload a mascot PNG to MinIO. Returns {url: presigned_url, filename: str}."""
    filename = await file_service.save_mascot_image(file)
    url = file_service.get_mascot_image_url(filename)
    return {"url": url, "filename": filename}
