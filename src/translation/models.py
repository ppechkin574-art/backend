"""Models for the admin question-translation workflow (Kazakh).

The translator itself is a Claude Code session (no in-backend LLM): the admin
exports untranslated questions to a file, the operator hands the file to Claude,
and uploads the translated file back. These tables hold the operator-facing
control state around that flow.

- TranslationGlossary — a reusable «standard pool» of word replacements
  (ru → kk), scoped per subject (`subject_id` NULL = global). Shipped inside the
  export file so the translation stays consistent for domain terms.
- TranslationConfig — saved translation parameters per subject (tone, length,
  free-text instruction). Also shipped inside the export file.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from database import Base


class TranslationGlossary(Base):
    __tablename__ = "translation_glossary"
    __table_args__ = (
        UniqueConstraint("subject_id", "term_ru", name="uq_glossary_subject_term"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # NULL subject_id = global term (applies to every subject).
    subject_id = Column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    term_ru = Column(String, nullable=False)
    term_kk = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Glossary {self.term_ru}→{self.term_kk} subj={self.subject_id}>"


class TranslationConfig(Base):
    __tablename__ = "translation_config"

    # One row per subject. No row → defaults (official / keep length).
    subject_id = Column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    tone = Column(String, nullable=False, server_default="official")  # conversational | official
    length = Column(String, nullable=False, server_default="keep")  # short | keep
    instruction = Column(Text, nullable=True)  # extra free-text instruction
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TranslationConfig subj={self.subject_id} {self.tone}/{self.length}>"
