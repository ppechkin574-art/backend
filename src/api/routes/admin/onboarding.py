"""Admin CRUD for onboarding stories and image uploads."""

from fastapi import APIRouter, Depends, File, UploadFile

from api.dependencies import allow_only_admins, get_file_service, get_onboarding_service
from onboarding.dtos import (
    OnboardingStepDTO,
    OnboardingStoryCreateDTO,
    OnboardingStoryDTO,
    OnboardingStoryUpdateDTO,
)
from onboarding.service import OnboardingService
from utils.file_service import FileService

router = APIRouter(
    prefix="/admin/onboarding",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


# ── Stories ──────────────────────────────────────────────────────────────────

@router.get("/stories", response_model=list[OnboardingStoryDTO])
def list_stories(service: OnboardingService = Depends(get_onboarding_service)):
    return [OnboardingStoryDTO.model_validate(s) for s in service.list_all()]


@router.post("/stories", response_model=OnboardingStoryDTO, status_code=201)
def create_story(
    body: OnboardingStoryCreateDTO,
    service: OnboardingService = Depends(get_onboarding_service),
):
    story = service.create_story(body)
    service.repo.db.commit()
    return OnboardingStoryDTO.model_validate(service.get_story(story.id))


@router.get("/stories/{story_id}", response_model=OnboardingStoryDTO)
def get_story(
    story_id: int,
    service: OnboardingService = Depends(get_onboarding_service),
):
    return OnboardingStoryDTO.model_validate(service.get_story(story_id))


@router.patch("/stories/{story_id}", response_model=OnboardingStoryDTO)
def update_story(
    story_id: int,
    body: OnboardingStoryUpdateDTO,
    service: OnboardingService = Depends(get_onboarding_service),
):
    story = service.update_story(story_id, body)
    service.repo.db.commit()
    return OnboardingStoryDTO.model_validate(service.get_story(story.id))


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(
    story_id: int,
    service: OnboardingService = Depends(get_onboarding_service),
):
    service.delete_story(story_id)
    service.repo.db.commit()


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
