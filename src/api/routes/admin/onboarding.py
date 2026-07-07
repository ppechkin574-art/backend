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
