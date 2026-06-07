"""Question-generator review pipeline — staging table for AI drafts.

AI-generated questions land here as `draft` rows. A human reviews /
edits them in the admin panel, then **publishes** — which builds a real
`questions` row (with its normalized `text_block_links` / `question_blocks`
/ `variants`) through the EXISTING question create service, and flips the
draft to `published` while recording the produced `published_question_id`.

Why a separate table (not just inserting into `questions` with a flag):
- The generator output is *unstructured-ish* — it carries provenance
  (`source` book/chapter/page), a verifier verdict (`validation`), a
  free-text `subject_name`/`topic_name` the model guessed, and a dedup
  hint. None of that belongs on the live `questions` row.
- Drafts are mutable scratch space — they can be rejected, re-edited,
  re-published. The live `questions` table stays clean: only reviewed,
  approved content ever reaches it, via the same create path used by
  the XLSX importer and the admin question form.

Content shape mirrors the create DTO so publish is a straight map:
- `blocks`  — JSON list of {type, order, value} → the question's blocks.
- `variants`— JSON list of {value | blocks, is_correct, weight} → the
  question's variants (each variant becomes its own block link).

Additive only: this table has NO FK *into* it from existing tables and
does not alter `questions`/`variants`/`question_blocks`.
"""

import uuid

from sqlalchemy import (
    JSON,
    UUID,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from database import Base
from quiz.dtos.enums import Difficulty, DraftStatus, QuestionType


class QuestionDraft(Base):
    __tablename__ = "question_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)

    # Subject can be referenced by id (when the generator already resolved
    # it) OR named (when it only knows the textbook's subject string). We
    # keep BOTH: publish resolves id-or-name via subject_service, and the
    # reviewer can see the raw name the model produced.
    subject_id = Column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    subject_name = Column(String, nullable=True)

    topic_name = Column(String, nullable=True)
    difficulty = Column(Enum(Difficulty), nullable=True)
    question_type = Column(
        Enum(QuestionType), nullable=False, default=QuestionType.single_choice
    )

    # Structured content, stored as JSON (Postgres `json`). Mirrors the
    # block / variant shapes consumed by QuestionCreateServiceDTO.
    #   blocks   : list[{type, order, value}]
    #   variants : list[{value | blocks, is_correct, weight}]
    blocks = Column(JSON, nullable=False, default=list)
    variants = Column(JSON, nullable=False, default=list)

    # «Что требует вопрос?» help-panel + post-test «Запомни» card — same
    # localized fields the live Question row carries, so publish copies
    # them straight across.
    task_description_ru = Column(Text, nullable=True)
    task_description_kk = Column(Text, nullable=True)
    question_translation_ru = Column(Text, nullable=True)
    question_translation_kk = Column(Text, nullable=True)
    explanation_ru = Column(Text, nullable=True)
    explanation_kk = Column(Text, nullable=True)

    # Provenance from the source textbook: {book, chapter, page}.
    source = Column(JSON, nullable=True)

    # Review lifecycle. Default `draft`; publish → `published`,
    # reject → `rejected`. `approved` is an optional intermediate the
    # reviewer can set before publishing.
    status = Column(
        Enum(DraftStatus), nullable=False, default=DraftStatus.draft
    )

    # Verifier output: {verdict, groundedness, dedup_similarity, confidence}.
    validation = Column(JSON, nullable=True)

    # If the generator flagged this as similar to an existing live
    # question, this points at it (advisory — does not block publish).
    dedup_of_question_id = Column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    # Set on publish — the live question this draft produced.
    published_question_id = Column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )

    reviewed_by = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_question_drafts_status", "status"),
        Index("ix_question_drafts_subject_id", "subject_id"),
    )
