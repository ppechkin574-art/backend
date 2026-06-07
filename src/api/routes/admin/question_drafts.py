"""Admin API for the AI question-generator review pipeline.

AI-generated questions land here as `draft` rows (POST by the generator
tool), a human reviews / edits them, then publishes — which materializes
a live `questions` row through the existing question create service.

Endpoints (all gated by `allow_only_admins`):
- POST   /admin/question-drafts                 — create (generator tool)
- GET    /admin/question-drafts                 — list (status / subject filters + pagination)
- GET    /admin/question-drafts/{id}            — get one
- PATCH  /admin/question-drafts/{id}            — edit before publish
- POST   /admin/question-drafts/{id}/publish    — → live question (returns its id)
- POST   /admin/question-drafts/{id}/reject     — mark rejected
- DELETE /admin/question-drafts/{id}            — hard delete

Commit is issued explicitly in the route (same convention as the
leaderboard-prize admin routes) so the draft state-change and the live
question create land together within the request.
"""

from fastapi import APIRouter, Depends, Query

from api.dependencies import allow_only_admins, get_question_draft_service
from quiz.dtos.enums import DraftStatus
from quiz.dtos.question_drafts import (
    QuestionDraftCreateDTO,
    QuestionDraftListDTO,
    QuestionDraftReadDTO,
    QuestionDraftUpdateDTO,
)
from quiz.services.question_drafts import QuestionDraftService

router = APIRouter(
    prefix="/admin/question-drafts",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.post("", response_model=QuestionDraftReadDTO, status_code=201)
def create_draft(
    body: QuestionDraftCreateDTO,
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    draft = service.create(body)
    service.repo.db.commit()
    service.repo.db.refresh(draft)
    return QuestionDraftReadDTO.model_validate(draft)


@router.get("", response_model=QuestionDraftListDTO)
def list_drafts(
    status: DraftStatus | None = Query(default=None),
    subject_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    items, total = service.list(
        status=status, subject_id=subject_id, limit=limit, offset=offset
    )
    return QuestionDraftListDTO(
        items=[QuestionDraftReadDTO.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{draft_id}", response_model=QuestionDraftReadDTO)
def get_draft(
    draft_id: int,
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    return QuestionDraftReadDTO.model_validate(service.get_one(draft_id))


@router.patch("/{draft_id}", response_model=QuestionDraftReadDTO)
def update_draft(
    draft_id: int,
    body: QuestionDraftUpdateDTO,
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    draft = service.update(draft_id, body)
    service.repo.db.commit()
    service.repo.db.refresh(draft)
    return QuestionDraftReadDTO.model_validate(draft)


@router.post("/{draft_id}/publish", response_model=QuestionDraftReadDTO)
async def publish_draft(
    draft_id: int,
    user=Depends(allow_only_admins),
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    reviewed_by = str(getattr(user, "id", None)) if user else None
    draft = await service.publish(draft_id, reviewed_by=reviewed_by)
    service.repo.db.commit()
    service.repo.db.refresh(draft)
    return QuestionDraftReadDTO.model_validate(draft)


@router.post("/{draft_id}/reject", response_model=QuestionDraftReadDTO)
def reject_draft(
    draft_id: int,
    user=Depends(allow_only_admins),
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    reviewed_by = str(getattr(user, "id", None)) if user else None
    draft = service.reject(draft_id, reviewed_by=reviewed_by)
    service.repo.db.commit()
    service.repo.db.refresh(draft)
    return QuestionDraftReadDTO.model_validate(draft)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(
    draft_id: int,
    service: QuestionDraftService = Depends(get_question_draft_service),
):
    service.delete(draft_id)
    service.repo.db.commit()
