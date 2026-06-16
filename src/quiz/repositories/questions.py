import builtins
import logging
from uuid import UUID

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from quiz.dtos.enums import Difficulty, QuestionType
from quiz.dtos.questions import (
    QuestionCreateRepositoryDTO,
    QuestionRepositoryDTO,
    QuestionUpdateRepositoryDTO,
)
from quiz.exceptions import QuestionNotFound, TopicNotFound
from quiz.models.edu_content import Hint, Question, Variant
from quiz.models.ent import EntOptionQuestion
from quiz.models.text_blocks import TextBlock, TextBlockLink
from quiz.models.trainer import TrainerQuestion
from quiz.services.base import BaseRepositoryInterface

logger = logging.getLogger(__name__)


class QuestionRepositoryInterface(
    BaseRepositoryInterface[QuestionCreateRepositoryDTO, QuestionUpdateRepositoryDTO, QuestionRepositoryDTO]
):
    """Interface for question data access operations with additional question-specific methods"""

    def list_query(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
        difficulty: list[Difficulty] | None = None,
        question_type: list[QuestionType] | None = None,
        subject_ids: list[int] | None = None,
        topic_ids: list[int] | None = None,
        usage_type: str | None = None,
    ) -> tuple[list[QuestionRepositoryDTO], int]:
        """
        Get paginated list of questions with advanced filtering

        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return
            search: Search string for question content
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction
            difficulty: Filter by difficulty levels
            question_type: Filter by question types
            subject_ids: Filter by subject IDs
            topic_ids: Filter by topic IDs

        Returns:
            Tuple of (list of QuestionRepositoryDTO, total count after filtering)
        """
        raise NotImplementedError

    def get_questions_in_trainers(self) -> list[QuestionRepositoryDTO]:
        """Get all questions that are included in trainers"""
        raise NotImplementedError

    def get_questions_in_ent_options(self) -> list[QuestionRepositoryDTO]:
        """Get all questions that are included in ENT options"""
        raise NotImplementedError

    # def get_questions_by_trainer_id(self, trainer_id: int) -> list[QuestionRepositoryDTO]:
    #     """Get questions by trainer ID"""
    #     raise NotImplementedError

    # def get_questions_by_ent_option_id(
    #     self, ent_option_id: int
    # ) -> list[QuestionRepositoryDTO]:
    #     """Get questions by ENT option ID"""
    #     raise NotImplementedError

    def get_questions_by_ids(self, question_ids: list[int]) -> list[QuestionRepositoryDTO]:
        """Get questions by ids preserving all blocks/variants"""
        raise NotImplementedError

    def get_subject_questions_stats(self) -> list[tuple[int, int]]:
        """Get question statistics by subject"""
        raise NotImplementedError

    def get_topic_questions_stats(self) -> list[tuple[int, int]]:
        """Get question statistics by topic"""
        raise NotImplementedError

    def count_by_subject(self, subject_id: int) -> int:
        """Count questions by subject"""
        raise NotImplementedError

    def count_by_topic(self, topic_id: int) -> int:
        """Count questions by topic"""
        raise NotImplementedError

    def get_answered_questions_by_trainer(self, student_guid: UUID, trainer_id: int) -> list[int]:
        """Get answered questions by student in trainer"""
        raise NotImplementedError

    def get_by_trainer_id(self, trainer_id: int) -> list[QuestionRepositoryDTO]:
        """Get questions by trainer ID"""
        raise NotImplementedError

    def get_by_topic_id(self, topic_id: int) -> list[QuestionRepositoryDTO]:
        """Get questions by topic ID"""
        raise NotImplementedError


class QuestionRepository(QuestionRepositoryInterface):
    """Implementation of question data access operations"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: QuestionCreateRepositoryDTO) -> QuestionRepositoryDTO:
        """
        Create a new question in database

        Args:
            create_dto: Data for question creation

        Returns:
            Created QuestionRepositoryDTO

        Raises:
            TopicNotFound: If specified topic doesn't exist
        """
        try:
            q = Question(
                topic_id=create_dto.topic_id,
                subject_id=create_dto.subject_id,
                difficulty=create_dto.difficulty,
                question_type=create_dto.type,
                task_description_ru=getattr(create_dto, "task_description_ru", None),
                task_description_kk=getattr(create_dto, "task_description_kk", None),
                question_translation_ru=getattr(create_dto, "question_translation_ru", None),
                question_translation_kk=getattr(create_dto, "question_translation_kk", None),
                explanation_ru=getattr(create_dto, "explanation_ru", None),
                explanation_kk=getattr(create_dto, "explanation_kk", None),
            )
            self._session.add(q)
            self._session.flush()

            if create_dto.blocks:
                question_link = TextBlockLink()
                self._session.add(question_link)
                self._session.flush()

                for block_dto in create_dto.blocks:
                    block = TextBlock(
                        text_block_link_id=question_link.id,
                        order=block_dto.order,
                        type=block_dto.type,
                        value=block_dto.value,
                    )
                    self._session.add(block)

                q.link = question_link

            if create_dto.hint and create_dto.hint.blocks:
                hint = Hint()
                self._session.add(hint)
                self._session.flush()

                hint_link = TextBlockLink()
                self._session.add(hint_link)
                self._session.flush()

                for block_dto in create_dto.hint.blocks:
                    block = TextBlock(
                        text_block_link_id=hint_link.id,
                        order=block_dto.order,
                        type=block_dto.type,
                        value=block_dto.value,
                    )
                    self._session.add(block)

                hint.link = hint_link
                q.hint = hint

            for variant_dto in create_dto.variants:
                v = Variant(
                    question_id=q.id,
                    is_correct=variant_dto.is_correct,
                    weight=variant_dto.weight,
                )
                self._session.add(v)
                self._session.flush()

                if variant_dto.blocks:
                    variant_link = TextBlockLink()
                    self._session.add(variant_link)
                    self._session.flush()

                    for block_dto in variant_dto.blocks:
                        block = TextBlock(
                            text_block_link_id=variant_link.id,
                            order=block_dto.order,
                            type=block_dto.type,
                            value=block_dto.value,
                        )
                        self._session.add(block)

                    v.link = variant_link

            self._session.flush()
            self._session.refresh(q)

            loaded_question = self._load_question_relationships(q)

            return QuestionRepositoryDTO.custom(loaded_question)

        except IntegrityError as e:
            self._session.rollback()
            if "questions_topic_id_fkey" in str(e):
                raise TopicNotFound(f"Topic with id {create_dto.topic_id} not found")
            else:
                raise

    def get_by_id(self, question_id: int) -> QuestionRepositoryDTO:
        """
        Get question by ID from database

        Args:
            question_id: ID of the question

        Returns:
            QuestionRepositoryDTO

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
        """
        question = (
            self._session.query(Question)
            .options(*self._get_question_loading_options())
            .filter(Question.id == question_id)
            .first()
        )

        if not question:
            raise QuestionNotFound(f"Question with id {question_id} not found")

        return QuestionRepositoryDTO.custom(question)

    # def get_by_guid(self, question_guid: UUID) -> QuestionRepositoryDTO:
    #     """
    #     Get question by GUID from database

    #     Args:
    #         question_guid: GUID of the question

    #     Returns:
    #         QuestionRepositoryDTO

    #     Raises:
    #         QuestionNotFound: If question with given GUID doesn't exist
    #     """
    #     question = (
    #         self._session.query(Question)
    #         .options(*self._get_question_loading_options())
    #         .filter(Question.guid == question_guid)
    #         .first()
    #     )

    #     if not question:
    #         raise QuestionNotFound(f"Question with guid {question_guid} not found")

    #     return QuestionRepositoryDTO.custom(question)

    def update(self, question_id: int, update_dto: QuestionUpdateRepositoryDTO) -> QuestionRepositoryDTO:
        """
        Update question by ID in database

        Args:
            question_id: ID of the question to update
            update_dto: Data for question update

        Returns:
            Updated QuestionRepositoryDTO

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
            TopicNotFound: If specified topic doesn't exist
        """
        try:
            query = self._session.query(Question).options(*self._get_question_loading_options())
            q = query.filter(Question.id == question_id).first()

            if not q:
                raise QuestionNotFound(f"Question with id {question_id} not found")
            old_hint = q.hint

            if update_dto.topic_id is not None:
                q.topic_id = update_dto.topic_id
            if update_dto.subject_id is not None:
                q.subject_id = update_dto.subject_id
            if update_dto.difficulty is not None:
                q.difficulty = update_dto.difficulty
            if update_dto.type is not None:
                q.question_type = update_dto.type
            # Help-panel fields. Guard on `is not None` exactly like every
            # sibling field above — otherwise a partial PATCH that omits them
            # (e.g. the subject/topic reassign in subjects.py / topics.py, which
            # builds QuestionUpdateRepositoryDTO with only subject_id) would
            # wipe authored panel content to NULL. The admin form sends the full
            # object, so clearing a field is done by sending "" (not None).
            for _f in (
                "task_description_ru",
                "task_description_kk",
                "question_translation_ru",
                "question_translation_kk",
                "explanation_ru",
                "explanation_kk",
            ):
                _val = getattr(update_dto, _f, None)
                if _val is not None:
                    setattr(q, _f, _val)

            if update_dto.blocks is not None:
                if q.link:
                    for block in q.link.blocks:
                        self._session.delete(block)
                    self._session.delete(q.link)

                if update_dto.blocks:
                    question_link = TextBlockLink()
                    self._session.add(question_link)
                    self._session.flush()

                    for block_dto in update_dto.blocks:
                        block = TextBlock(
                            text_block_link_id=question_link.id,
                            order=block_dto.order,
                            type=block_dto.type,
                            value=block_dto.value,
                        )
                        self._session.add(block)

                    q.link = question_link

            if update_dto.hint is not None:
                if update_dto.hint.blocks:
                    hint = Hint()
                    self._session.add(hint)
                    self._session.flush()

                    hint_link = TextBlockLink()
                    self._session.add(hint_link)
                    self._session.flush()

                    for block_dto in update_dto.hint.blocks:
                        block = TextBlock(
                            text_block_link_id=hint_link.id,
                            order=block_dto.order,
                            type=block_dto.type,
                            value=block_dto.value,
                        )
                        self._session.add(block)

                    hint.link = hint_link
                    q.hint = hint
                    self._session.flush()

                else:
                    q.hint = None
                    self._session.flush()

            if update_dto.variants:
                for variant in q.variants:
                    if variant.link:
                        for block in variant.link.blocks:
                            self._session.delete(block)
                        self._session.delete(variant.link)
                    self._session.delete(variant)

                for variant_dto in update_dto.variants:
                    v = Variant(
                        question_id=q.id,
                        is_correct=variant_dto.is_correct,
                        weight=variant_dto.weight,
                    )

                    if hasattr(variant_dto, "blocks") and variant_dto.blocks:
                        variant_link = TextBlockLink()
                        self._session.add(variant_link)
                        self._session.flush()

                        for block_dto in variant_dto.blocks:
                            block = TextBlock(
                                text_block_link_id=variant_link.id,
                                order=block_dto.order,
                                type=block_dto.type,
                                value=block_dto.value,
                            )
                            self._session.add(block)

                        v.link = variant_link

                    self._session.add(v)

            if old_hint and old_hint != q.hint:
                if old_hint.link:
                    for block in old_hint.link.blocks:
                        self._session.delete(block)
                    self._session.delete(old_hint.link)
                self._session.delete(old_hint)

            self._session.flush()
            self._session.refresh(q)

            return QuestionRepositoryDTO.custom(q)

        except IntegrityError as e:
            self._session.rollback()
            if "questions_topic_id_fkey" in str(e):
                raise TopicNotFound(f"Topic with id {update_dto.topic_id} not found")
            else:
                raise

    def delete(self, question_id: int) -> None:
        """
        Delete question by ID from database

        Args:
            question_id: ID of the question to delete

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
        """
        question = self._session.query(Question).filter(Question.id == question_id).first()

        if not question:
            raise QuestionNotFound(f"Question with id {question_id} not found")

        self._session.delete(question)
        self._session.flush()

    def _get_question_loading_options(self):
        """Get SQLAlchemy loading options for question relationships"""
        return [
            selectinload(Question.variants).selectinload(Variant.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.hint).selectinload(Hint.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.topic),
            selectinload(Question.subject),
            selectinload(Question.link).selectinload(TextBlockLink.blocks),
        ]

    def _load_question_relationships(self, question: Question) -> Question:
        """Eager load question relationships with proper loading options"""
        return (
            self._session.query(Question)
            .options(
                selectinload(Question.link).selectinload(TextBlockLink.blocks),
                selectinload(Question.hint).selectinload(Hint.link).selectinload(TextBlockLink.blocks),
                selectinload(Question.variants).selectinload(Variant.link).selectinload(TextBlockLink.blocks),
                selectinload(Question.topic),
                selectinload(Question.subject),
            )
            .filter(Question.id == question.id)
            .first()
        )

    def _build_search_query(self, query, search: str):
        """Build search query for questions"""
        if not search:
            return query

        search_term = f"%{search}%"

        return query.filter(
            or_(
                Question.link.has(TextBlockLink.blocks.any(TextBlock.value.ilike(search_term))),
                Question.variants.any(Variant.link.has(TextBlockLink.blocks.any(TextBlock.value.ilike(search_term)))),
                Question.hint.has(Hint.link.has(TextBlockLink.blocks.any(TextBlock.value.ilike(search_term)))),
            )
        )

    def list(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[QuestionRepositoryDTO], int]:
        """
        Get paginated list of questions from database
        """
        q = self._session.query(Question).options(*self._get_question_loading_options())

        q = self._build_search_query(q, search)

        filtered_count = q.count()

        if sort_columns and is_sort_ascendings:
            order_criteria = []
            for i, sort_column in enumerate(sort_columns):
                if sort_column and hasattr(Question, sort_column):
                    attr = getattr(Question, sort_column)
                    order_criteria.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_criteria:
                q = q.order_by(*order_criteria)
        else:
            q = q.order_by(Question.id.desc())

        q = q.offset(offset).limit(limit)

        questions = q.all()
        return [QuestionRepositoryDTO.custom(r) for r in questions], filtered_count

    def list_query(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
        difficulty: builtins.list[Difficulty] | None = None,
        question_type: builtins.list[QuestionType] | None = None,
        subject_ids: builtins.list[int] | None = None,
        topic_ids: builtins.list[int] | None = None,
        usage_type: str | None = None,
    ) -> tuple[builtins.list[QuestionRepositoryDTO], int]:
        """
        Get paginated list of questions with advanced filtering
        """
        q = self._session.query(Question).options(*self._get_question_loading_options())

        q = self._build_search_query(q, search)

        if difficulty:
            q = q.filter(Question.difficulty.in_([d.value for d in difficulty]))

        if question_type:
            q = q.filter(Question.question_type.in_([qt.value for qt in question_type]))

        if subject_ids:
            q = q.filter(Question.subject_id.in_(subject_ids))

        if topic_ids:
            q = q.filter(Question.topic_id.in_(topic_ids))

        if usage_type:
            q = self._apply_usage_filter(q, usage_type)

        filtered_count = q.count()

        if sort_columns and is_sort_ascendings:
            order_criteria = []
            for i, sort_column in enumerate(sort_columns):
                if sort_column and hasattr(Question, sort_column):
                    attr = getattr(Question, sort_column)
                    order_criteria.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_criteria:
                q = q.order_by(*order_criteria)
        else:
            q = q.order_by(Question.id.asc())

        q = q.offset(offset).limit(limit)

        questions = q.all()
        return [QuestionRepositoryDTO.custom(r) for r in questions], filtered_count

    def get_questions_in_trainers(self) -> builtins.list[QuestionRepositoryDTO]:
        """Get all questions that are included in trainers"""
        questions = (
            self._session.query(Question)
            .join(TrainerQuestion)
            .options(*self._get_question_loading_options())
            .distinct()
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_questions_in_ent_options(self) -> builtins.list[QuestionRepositoryDTO]:
        """Get all questions that are included in ENT options"""
        questions = (
            self._session.query(Question)
            .join(EntOptionQuestion)
            .options(*self._get_question_loading_options())
            .distinct()
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    # def get_questions_by_trainer_id(
    #     self, trainer_id: int
    # ) -> builtins.list[QuestionRepositoryDTO]:
    #     """Get questions by trainer ID"""
    #     questions = (
    #         self._session.query(Question)
    #         .join(TrainerQuestion)
    #         .options(*self._get_question_loading_options())
    #         .filter(TrainerQuestion.trainer_id == trainer_id)
    #         .all()
    #     )

    #     return [QuestionRepositoryDTO.custom(q) for q in questions]

    # def get_questions_by_ent_option_id(
    #     self, ent_option_id: int
    # ) -> builtins.list[QuestionRepositoryDTO]:
    #     """Get questions by ENT option ID"""
    #     questions = (
    #         self._session.query(Question)
    #         .join(EntOptionQuestion)
    #         .options(*self._get_question_loading_options())
    #         .filter(EntOptionQuestion.ent_option_id == ent_option_id)
    #         .all()
    #     )

    #     return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_questions_by_ids(self, question_ids: builtins.list[int]) -> builtins.list[QuestionRepositoryDTO]:
        """Get questions by ids preserving all blocks/variants"""
        if not question_ids:
            return []

        questions = (
            self._session.query(Question)
            .options(*self._get_question_loading_options())
            .filter(Question.id.in_(question_ids))
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_subject_questions_stats(self) -> builtins.list[tuple[int, int]]:
        """Get question statistics by subject"""
        return self._session.query(Question.subject_id, func.count(Question.id)).group_by(Question.subject_id).all()

    def get_topic_questions_stats(self) -> builtins.list[tuple[int, int]]:
        """Get question statistics by topic"""
        return self._session.query(Question.topic_id, func.count(Question.id)).group_by(Question.topic_id).all()

    def count_by_subject(self, subject_id: int) -> int:
        """Count questions by subject"""
        return self._session.query(Question).filter_by(subject_id=subject_id).count()

    def count_by_topic(self, topic_id: int) -> int:
        """Count questions by topic"""
        return self._session.query(Question).filter_by(topic_id=topic_id).count()

    def count_all_by_subject(self) -> dict[int, int]:
        """Single query: {subject_id: question_count} for all subjects."""
        rows = (
            self._session.query(Question.subject_id, func.count(Question.id))
            .group_by(Question.subject_id)
            .all()
        )
        return {subject_id: count for subject_id, count in rows}

    def count_all_by_topic(self) -> dict[int, int]:
        """Single query: {topic_id: question_count} for all topics."""
        rows = (
            self._session.query(Question.topic_id, func.count(Question.id))
            .group_by(Question.topic_id)
            .all()
        )
        return {topic_id: count for topic_id, count in rows}

    def get_answered_questions_by_trainer(self, student_guid: UUID, trainer_id: int) -> builtins.list[int]:
        """Get answered questions by student in trainer"""
        query = text(
            """
            SELECT DISTINCT q.id as question_id
            FROM trainer_attempt_answers taa
            JOIN trainer_attempt_questions taq ON taa.trainer_attempt_question_id = taq.id
            JOIN trainer_attempts ta ON taq.trainer_attempt_id = ta.id
            JOIN questions q ON taq.question_id = q.id
            JOIN trainer_questions tq ON q.id = tq.question_id
            WHERE ta.student_guid = :student_guid
            AND tq.trainer_id = :trainer_id
            AND taa.student_guid = :student_guid
        """
        )

        result = self._session.execute(query, {"student_guid": student_guid, "trainer_id": trainer_id})

        return [row[0] for row in result]

    def get_by_trainer_id(self, trainer_id: int) -> builtins.list[QuestionRepositoryDTO]:
        """Get questions by trainer ID"""
        questions = (
            self._session.query(Question)
            .join(TrainerQuestion)
            .options(*self._get_question_loading_options())
            .filter(TrainerQuestion.trainer_id == trainer_id)
            .order_by(Question.id)
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def get_by_topic_id(self, topic_id: int) -> builtins.list[QuestionRepositoryDTO]:
        """Get questions by topic ID"""
        questions = (
            self._session.query(Question)
            .options(*self._get_question_loading_options())
            .filter(Question.topic_id == topic_id)
            .all()
        )

        return [QuestionRepositoryDTO.custom(q) for q in questions]

    # Legacy methods for backward compatibility
    def add(self, question: QuestionCreateRepositoryDTO) -> QuestionRepositoryDTO:
        """Legacy method for backward compatibility"""
        return self.create(question)

    # def update_only_question(self, question: QuestionRepositoryDTO) -> None:
    #     """Legacy method for backward compatibility"""
    #     update_dto = QuestionUpdateRepositoryDTO(
    #         topic_id=question.topic_id,
    #         subject_id=question.subject_id,
    #         difficulty=question.difficulty,
    #         type=question.type,
    #     )
    #     self.update(question.id, update_dto)

    # def bulk_add(
    #     self, questions: builtins.list[QuestionCreateRepositoryDTO]
    # ) -> builtins.list[QuestionRepositoryDTO]:
    #     """Legacy method for backward compatibility"""
    #     results = []
    #     for question in questions:
    #         results.append(self.create(question))
    #     return results

    def get_questions_by_subject(self, subject_id: int) -> builtins.list[QuestionRepositoryDTO]:
        """Получить вопросы по subject_id - возвращает DTO"""
        questions = (
            self._session.query(Question)
            .options(*self._get_question_loading_options())
            .filter(Question.subject_id == subject_id)
            .all()
        )
        return [QuestionRepositoryDTO.custom(q) for q in questions]

    def _apply_usage_filter(self, query, usage_type: str):
        """Применяет фильтр по использованию вопросов"""
        if usage_type == "training":
            return query.filter(Question.trainers.any())
        elif usage_type == "ent":
            return query.filter(Question.ent_options.any())
        elif usage_type == "unassigned":
            from sqlalchemy import not_

            return query.filter(not_(Question.trainers.any()), not_(Question.ent_options.any()))
        elif usage_type == "all":
            return query
        else:
            return query

    # def get_questions_with_subjects(
    #     self, question_ids: builtins.list[int]
    # ) -> builtins.list[Any]:
    #     """Получить вопросы с загруженными предметами"""
    #     logger.info(
    #         "get_questions_with_subjects called with %s question_ids", len(question_ids)
    #     )

    #     if not question_ids:
    #         logger.warning("get_questions_with_subjects: empty question_ids list")
    #         return []

    #     questions = (
    #         self._session.query(Question)
    #         .options(joinedload(Question.subject))
    #         .filter(Question.id.in_(question_ids))
    #         .all()
    #     )

    #     logger.info(
    #         "get_questions_with_subjects: returning %s questions", len(questions)
    #     )
    #     if questions:
    #         first_question = questions[0]
    #         logger.info("First question type: %s", type(first_question))
    #         logger.info("First question id: %s", first_question.id)
    #         logger.info(
    #             "First question has subject_id: %s",
    #             hasattr(first_question, "subject_id"),
    #         )
    #         logger.info(
    #             "First question has subject: %s", hasattr(first_question, "subject")
    #         )

    #         if hasattr(first_question, "subject") and first_question.subject:
    #             subject = first_question.subject
    #             logger.info("Subject type: %s", type(subject))
    #             logger.info("Subject id: %s", subject.id)
    #             logger.info("Subject name: %s", subject.name)
    #         else:
    #             logger.warning("First question has no subject or subject is None")

    #     return questions
