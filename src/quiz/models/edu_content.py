import uuid

from sqlalchemy import UUID, Boolean, Column, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base
from quiz.dtos.enums import Difficulty, QuestionType, SubjectType


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(Enum(SubjectType), nullable=True, default=SubjectType.main)
    image = Column(String, nullable=False, default="")

    topics = relationship("Topic", back_populates="subject", passive_deletes=True)
    questions = relationship("Question", back_populates="subject", passive_deletes=True)
    ent_options = relationship("EntOption", back_populates="subject", passive_deletes=True)
    modules = relationship(
        "SubjectModule",
        back_populates="subject",
        passive_deletes=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return self.name


class Topic(Base):
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    subject_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, unique=True, nullable=False)
    # Kazakh cache column (Phase 7b). Nullable; null → fall back to `name`.
    name_kk = Column(String, nullable=True)
    difficulty = Column(Enum(Difficulty), nullable=True)

    subject = relationship(Subject, back_populates="topics", passive_deletes=True)
    questions = relationship("Question", back_populates="topic", passive_deletes=True)
    trainers = relationship("Trainer", back_populates="topic", passive_deletes=True)
    module_lessons = relationship(
        "ModuleLesson",
        back_populates="topic",
        passive_deletes=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return self.name


class Variant(Base):
    __tablename__ = "variants"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    weight = Column(
        Float, default=0, nullable=False
    )  # Вес ответа (1 если правильный ответ один, 1/количество правильных ответов, если их несколько)
    is_correct = Column(Boolean, default=False, nullable=False)  # убрать после добавления веса

    # Phase 7b kk cache — same pattern as Question.question_text_kk.
    # Populated by alembic e7d8c9b1a2f3 for Math; null elsewhere → RU
    # fallback at the api/dto layer.  Read by the kk-splice helpers in
    # quiz.services.ent_attempts (create flow) and the get_attempt_detail
    # results path.
    variant_text_kk = Column(Text, nullable=True)

    question = relationship("Question", back_populates="variants", passive_deletes=True)
    link = relationship(
        "TextBlockLink",
        back_populates="variant",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
        passive_deletes=True,
    )


class Hint(Base):
    __tablename__ = "hints"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)

    question = relationship("Question", back_populates="hint", passive_deletes=True)
    link = relationship(
        "TextBlockLink",
        back_populates="hint",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
        passive_deletes=True,
    )


class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True)
    guid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    topic_id = Column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    subject_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    hint_id = Column(ForeignKey("hints.id", ondelete="CASCADE"), nullable=True)
    difficulty = Column(Enum(Difficulty), nullable=True)
    question_type = Column(Enum(QuestionType), nullable=True, default=QuestionType.single_choice)

    # Kazakh cache columns (Phase 7b pilot — Mathematics-only for now).
    # Read by api-side locale resolver when Accept-Language: kk is set.
    # Null → fall back to building text from `link.blocks` as before.
    # `hint_text_kk` is denormalised onto the question row to avoid an
    # extra join through `hints` — see migration a7c4f9e1b2d8 for the
    # rationale.
    question_text_kk = Column(Text, nullable=True)
    hint_text_kk = Column(Text, nullable=True)

    # «Что требует вопрос?» help panel (authored in admin, served by locale).
    # Two independent localized strings per question, both nullable — the app
    # only shows the panel when the locale-resolved pair is non-empty. Unlike
    # question_text_kk these have NO blocks fallback, so each locale needs its
    # own column. See migration b1f2a3c4d5e6.
    #  * task_description_* — what the question asks ("Выберите правильную…").
    #  * question_translation_* — the question text rendered in that language.
    task_description_ru = Column(Text, nullable=True)
    task_description_kk = Column(Text, nullable=True)
    question_translation_ru = Column(Text, nullable=True)
    question_translation_kk = Column(Text, nullable=True)
    # Post-test review «Запомни» card — a short memorisation rule / why the
    # correct answer is correct. Localized, nullable, served in review payloads.
    # See migration c2a3b4d5e6f7.
    explanation_ru = Column(Text, nullable=True)
    explanation_kk = Column(Text, nullable=True)

    topic = relationship("Topic", back_populates="questions", passive_deletes=True)
    subject = relationship("Subject", back_populates="questions", passive_deletes=True)
    hint = relationship("Hint", back_populates="question", passive_deletes=True)
    variants = relationship(
        "Variant",
        back_populates="question",
        cascade="all, delete-orphan",
        single_parent=True,
        passive_deletes=True,
    )
    trainer_questions = relationship(
        "TrainerQuestion",
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    ent_options = relationship(
        "EntOptionQuestion",
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    trainer_attempt_questions = relationship("TrainerAttemptQuestion", back_populates="question", passive_deletes=True)
    link = relationship(
        "TextBlockLink",
        back_populates="question",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
        passive_deletes=True,
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Инициализируем variants как пустую коллекцию SQLAlchemy
        if not hasattr(self, "variants") or self.variants is None:
            self.variants = []
