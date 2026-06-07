"""Thin DB layer for the `question_drafts` table.

No business logic — that lives in the service. Mirrors the
leaderboard-prize repository: a plain SQLAlchemy `Session`, explicit
`flush()` on writes, `commit()` left to the route (so the publish flow
can coordinate the draft write with the live-question create in one
request lifecycle).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quiz.dtos.enums import DraftStatus
from quiz.models.question_drafts import QuestionDraft


class QuestionDraftRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        status: DraftStatus | None = None,
        subject_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QuestionDraft], int]:
        """Filtered, paginated list + total count (for the same filters)."""
        conditions = []
        if status is not None:
            conditions.append(QuestionDraft.status == status)
        if subject_id is not None:
            conditions.append(QuestionDraft.subject_id == subject_id)

        base = select(QuestionDraft)
        count_q = select(func.count()).select_from(QuestionDraft)
        for cond in conditions:
            base = base.where(cond)
            count_q = count_q.where(cond)

        total = self.db.scalar(count_q) or 0
        rows = list(
            self.db.scalars(
                base.order_by(QuestionDraft.created_at.desc(), QuestionDraft.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return rows, total

    def get(self, draft_id: int) -> QuestionDraft | None:
        return self.db.get(QuestionDraft, draft_id)

    def create(self, draft: QuestionDraft) -> QuestionDraft:
        self.db.add(draft)
        self.db.flush()
        return draft

    def delete(self, draft: QuestionDraft) -> None:
        self.db.delete(draft)
        self.db.flush()
