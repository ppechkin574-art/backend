from datetime import datetime, timezone, UTC
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from onboarding.models import OnboardingStep, OnboardingStory, UserOnboardingView


class OnboardingRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── Stories ──────────────────────────────────────────────────────────────

    def list_all(self) -> list[OnboardingStory]:
        return list(
            self.db.scalars(
                select(OnboardingStory)
                .options(selectinload(OnboardingStory.steps))
                .order_by(OnboardingStory.priority.desc(), OnboardingStory.id)
            ).all()
        )

    def list_active(self) -> list[OnboardingStory]:
        return list(
            self.db.scalars(
                select(OnboardingStory)
                .options(selectinload(OnboardingStory.steps))
                .where(OnboardingStory.is_active.is_(True))
                .order_by(OnboardingStory.priority.desc(), OnboardingStory.id)
            ).all()
        )

    def get_story(self, story_id: int) -> OnboardingStory | None:
        return self.db.scalar(
            select(OnboardingStory)
            .options(selectinload(OnboardingStory.steps))
            .where(OnboardingStory.id == story_id)
        )

    def create_story(self, story: OnboardingStory) -> OnboardingStory:
        self.db.add(story)
        self.db.flush()
        return story

    def delete_story(self, story: OnboardingStory) -> None:
        self.db.delete(story)
        self.db.flush()

    # ── Steps ────────────────────────────────────────────────────────────────

    def get_step(self, step_id: int) -> OnboardingStep | None:
        return self.db.get(OnboardingStep, step_id)

    def create_step(self, step: OnboardingStep) -> OnboardingStep:
        self.db.add(step)
        self.db.flush()
        return step

    def delete_step(self, step: OnboardingStep) -> None:
        self.db.delete(step)
        self.db.flush()

    # ── View tracking ────────────────────────────────────────────────────────

    def get_view(self, user_id: UUID, story_id: int) -> UserOnboardingView | None:
        return self.db.scalar(
            select(UserOnboardingView).where(
                UserOnboardingView.user_id == user_id,
                UserOnboardingView.story_id == story_id,
            )
        )

    def get_views_for_user(self, user_id: UUID) -> list[UserOnboardingView]:
        return list(
            self.db.scalars(
                select(UserOnboardingView).where(UserOnboardingView.user_id == user_id)
            ).all()
        )

    def count_views(self, story_id: int) -> int:
        return self.db.scalar(
            select(func.count()).select_from(UserOnboardingView).where(UserOnboardingView.story_id == story_id)
        ) or 0

    def reset_views_all(self, story_id: int) -> int:
        result = self.db.execute(
            delete(UserOnboardingView).where(UserOnboardingView.story_id == story_id)
        )
        self.db.flush()
        return result.rowcount

    def reset_views_before_date(self, story_id: int, before_date: datetime) -> int:
        result = self.db.execute(
            delete(UserOnboardingView).where(
                UserOnboardingView.story_id == story_id,
                UserOnboardingView.created_at < before_date,
            )
        )
        self.db.flush()
        return result.rowcount

    def reset_views_for_user(self, story_id: int, user_id: UUID) -> int:
        result = self.db.execute(
            delete(UserOnboardingView).where(
                UserOnboardingView.story_id == story_id,
                UserOnboardingView.user_id == user_id,
            )
        )
        self.db.flush()
        return result.rowcount

    def upsert_view(self, user_id: UUID, story_id: int, skipped: bool) -> UserOnboardingView:
        view = self.get_view(user_id, story_id)
        now = datetime.now(UTC)
        if view is None:
            view = UserOnboardingView(
                user_id=user_id,
                story_id=story_id,
                view_count=1,
                skipped_at=now if skipped else None,
                completed_at=now if not skipped else None,
            )
            self.db.add(view)
        else:
            view.view_count += 1
            if skipped:
                view.skipped_at = now
            else:
                view.completed_at = now
        self.db.flush()
        return view
