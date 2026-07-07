from uuid import UUID

from fastapi import HTTPException, status

# Phones allowed to see is_test=True stories. Normalise: digits only, no spaces.
_TEST_PHONES: frozenset[str] = frozenset({"+77787943760"})

from onboarding.dtos import (
    OnboardingStoryCreateDTO, OnboardingStoryUpdateDTO,
    OnboardingViewDTO, OnboardingViewResponseDTO,
)
from onboarding.models import OnboardingStep, OnboardingStory
from onboarding.repository import OnboardingRepository


class OnboardingService:
    def __init__(self, repo: OnboardingRepository):
        self.repo = repo

    # ── Stories (admin) ──────────────────────────────────────────────────────

    def list_all(self) -> list[OnboardingStory]:
        return self.repo.list_all()

    def list_active(self, user_phone: str | None = None) -> list[OnboardingStory]:
        stories = self.repo.list_active()
        # is_test stories are only visible to phones in ONBOARDING_TEST_PHONES
        if user_phone not in _TEST_PHONES:
            stories = [s for s in stories if not s.is_test]
        return stories

    def get_story(self, story_id: int) -> OnboardingStory:
        story = self.repo.get_story(story_id)
        if story is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Онбординг-рассказ {story_id} не найден",
            )
        return story

    @staticmethod
    def _check_no_duplicate_step_orders(steps: list) -> None:
        orders = [s.step_order for s in steps]
        if len(orders) != len(set(orders)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Номера шагов (step_order) должны быть уникальными",
            )

    def create_story(self, payload: OnboardingStoryCreateDTO) -> OnboardingStory:
        self._check_no_duplicate_step_orders(payload.steps)
        story = OnboardingStory(
            name=payload.name,
            priority=payload.priority,
            is_active=payload.is_active,
            is_mandatory=payload.is_mandatory,
            is_test=payload.is_test,
            skip_delay_seconds=payload.skip_delay_seconds,
            target_audience=payload.target_audience,
            new_user_days=payload.new_user_days,
            trigger=payload.trigger,
            immediate_count=payload.immediate_count,
            max_shows_per_user=payload.max_shows_per_user,
            start_screen=payload.start_screen,
        )
        self.repo.create_story(story)
        for step_dto in payload.steps:
            step = OnboardingStep(story_id=story.id, **step_dto.model_dump())
            self.repo.create_step(step)
        self.repo.db.refresh(story)
        return story

    def update_story(self, story_id: int, payload: OnboardingStoryUpdateDTO) -> OnboardingStory:
        story = self.get_story(story_id)
        steps_payload = payload.steps
        fields = payload.model_dump(exclude_unset=True, exclude={"steps"})
        for field, value in fields.items():
            setattr(story, field, value)

        if steps_payload is not None:
            if len(steps_payload) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="История должна содержать хотя бы 1 шаг",
                )
            self._check_no_duplicate_step_orders(steps_payload)
            # Replace all steps
            for step in list(story.steps):
                self.repo.delete_step(step)
            for step_dto in steps_payload:
                step = OnboardingStep(story_id=story.id, **step_dto.model_dump())
                self.repo.create_step(step)
            self.repo.db.refresh(story)
        else:
            self.repo.db.flush()
        return story

    def delete_story(self, story_id: int) -> None:
        story = self.get_story(story_id)
        self.repo.delete_story(story)

    # ── Steps (admin) ────────────────────────────────────────────────────────

    def get_step(self, step_id: int) -> OnboardingStep:
        step = self.repo.get_step(step_id)
        if step is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Шаг {step_id} не найден",
            )
        return step

    def delete_step(self, step_id: int) -> None:
        step = self.get_step(step_id)
        self.repo.delete_step(step)

    # ── View tracking (app) ──────────────────────────────────────────────────

    def record_view(self, user_id: UUID, payload: OnboardingViewDTO) -> OnboardingViewResponseDTO:
        self.get_story(payload.story_id)  # raises 404 if story doesn't exist
        view = self.repo.upsert_view(user_id, payload.story_id, payload.skipped)
        return OnboardingViewResponseDTO(
            story_id=view.story_id,
            view_count=view.view_count,
            completed_at=view.completed_at,
            skipped_at=view.skipped_at,
        )

    def get_user_views(self, user_id: UUID) -> dict[int, int]:
        """Returns {story_id: view_count} for this user."""
        return {v.story_id: v.view_count for v in self.repo.get_views_for_user(user_id)}
