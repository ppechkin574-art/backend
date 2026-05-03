import builtins

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quiz.dtos.topic import (
    TopicCreateRepositoryDTO,
    TopicRepositoryDTO,
    TopicUpdateRepositoryDTO,
)
from quiz.exceptions import (
    TopicIdViolatesNotNullRepository,
    TopicNotFoundRepository,
    TopicSameNameRepository,
    TopicSubjectNotFoundRepository,
)
from quiz.models.edu_content import Question, Subject, Topic
from quiz.models.trainer import Trainer
from quiz.services.base import BaseRepositoryInterface


class TopicRepositoryInterface(
    BaseRepositoryInterface[TopicCreateRepositoryDTO, TopicUpdateRepositoryDTO, TopicRepositoryDTO]
):
    """Interface for topic data access operations"""

    def get_by_subject(
        self,
        subject_id: int,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[TopicRepositoryDTO], int]:
        """
        Get topics for a specific subject with pagination

        Args:
            subject_id: ID of the subject
            offset: Number of records to skip
            limit: Maximum number of records to return
            search: Search string for topic names
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction (True for ascending)

        Returns:
            Tuple of (list of TopicRepositoryDTO, total count after filtering)
        """
        raise NotImplementedError

    def get_by_name_and_subject(self, name: str, subject_id: int) -> TopicRepositoryDTO:
        """
        Get topic by name and subject ID

        Args:
            name: Name of the topic
            subject_id: ID of the subject

        Returns:
            TopicRepositoryDTO

        Raises:
            TopicNotFoundRepository: If topic with given name and subject doesn't exist
        """
        raise NotImplementedError

    def count_questions(self, topic_id: int) -> int:
        """
        Count number of questions in a topic

        Args:
            topic_id: ID of the topic

        Returns:
            Number of questions
        """
        raise NotImplementedError

    def get_with_question_counts(self) -> list[tuple[TopicRepositoryDTO, int]]:
        """
        Get all topics with their question counts

        Returns:
            List of tuples (TopicRepositoryDTO, question_count)
        """
        raise NotImplementedError

    def get_by_subject_with_stats(self, subject_id: int) -> list[tuple[TopicRepositoryDTO, int]]:
        """
        Get topics for a subject with question count statistics

        Args:
            subject_id: ID of the subject

        Returns:
            List of tuples (TopicRepositoryDTO, question_count)
        """
        raise NotImplementedError

    # def get_id_by_name(self, name: str) -> int:
    #     """
    #     Get topic ID by name

    #     Args:
    #         name: Topic name

    #     Returns:
    #         Topic ID

    #     Raises:
    #         TopicNotFoundRepository: If topic with given name doesn't exist
    #     """
    #     raise NotImplementedError

    def get_by_subject_id(self, subject_id: int) -> list[TopicRepositoryDTO]:
        """
        Get all topics for a specific subject

        Args:
            subject_id: ID of the subject

        Returns:
            List of TopicRepositoryDTO
        """
        raise NotImplementedError


class TopicRepository(TopicRepositoryInterface):
    """Implementation of topic data access operations"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: TopicCreateRepositoryDTO) -> TopicRepositoryDTO:
        """
        Create a new topic in database

        Args:
            create_dto: Data for topic creation

        Returns:
            Created TopicRepositoryDTO

        Raises:
            TopicSameNameRepository: If topic with same name already exists in subject
            TopicSubjectNotFoundRepository: If specified subject doesn't exist
        """
        # Check if subject exists
        subject = self._session.get(Subject, create_dto.subject_id)
        if subject is None:
            raise TopicSubjectNotFoundRepository(f"Subject with ID {create_dto.subject_id} not found")

        # Check for duplicate name in same subject
        existing_topic = (
            self._session.execute(
                select(Topic).where(
                    Topic.name == create_dto.name,
                    Topic.subject_id == create_dto.subject_id,
                )
            )
            .scalars()
            .first()
        )

        if existing_topic:
            raise TopicSameNameRepository(
                f"Topic '{existing_topic.name}' already exists in subject",
                existing_topic_id=existing_topic.id,
            )

        instance = Topic(**create_dto.model_dump())
        self._session.add(instance)
        self._session.flush()

        return TopicRepositoryDTO.model_validate(instance)

    def get_by_id(self, topic_id: int) -> TopicRepositoryDTO:
        """
        Get topic by ID from database

        Args:
            topic_id: ID of the topic

        Returns:
            TopicRepositoryDTO

        Raises:
            TopicNotFoundRepository: If topic with given ID doesn't exist
        """
        instance = self._session.get(Topic, topic_id)
        if instance is None:
            raise TopicNotFoundRepository
        return TopicRepositoryDTO.model_validate(instance)

    def update(self, topic_id: int, update_dto: TopicUpdateRepositoryDTO) -> TopicRepositoryDTO:
        """
        Update topic by ID in database

        Args:
            topic_id: ID of the topic to update
            update_dto: Data for topic update

        Returns:
            Updated TopicRepositoryDTO

        Raises:
            TopicNotFoundRepository: If topic with given ID doesn't exist
            TopicSameNameRepository: If update would create duplicate topic name in subject
            TopicSubjectNotFoundRepository: If specified subject doesn't exist
        """
        instance = self._session.get(Topic, topic_id)
        if instance is None:
            raise TopicNotFoundRepository

        # Check if subject exists (if subject_id is being updated)
        update_data = update_dto.model_dump(exclude_unset=True)
        if "subject_id" in update_data:
            subject = self._session.get(Subject, update_data["subject_id"])
            if subject is None:
                raise TopicSubjectNotFoundRepository

        # Check for duplicate name in same subject
        if "name" in update_data or "subject_id" in update_data:
            name = update_data.get("name", instance.name)
            subject_id = update_data.get("subject_id", instance.subject_id)

            existing_topic = (
                self._session.execute(
                    select(Topic).where(
                        Topic.name == name,
                        Topic.subject_id == subject_id,
                        Topic.id != topic_id,
                    )
                )
                .scalars()
                .first()
            )

            if existing_topic:
                raise TopicSameNameRepository

        for key, value in update_data.items():
            setattr(instance, key, value)

        self._session.flush()
        return TopicRepositoryDTO.model_validate(instance)

    def delete(self, topic_id: int) -> None:
        """
        Delete topic by ID from database

        Args:
            topic_id: ID of the topic to delete

        Raises:
            TopicNotFoundRepository: If topic with given ID doesn't exist
            TopicIdViolatesNotNullRepository: If topic cannot be deleted due to foreign key constraints
        """
        instance = self._session.get(Topic, topic_id)
        if instance is None:
            raise TopicNotFoundRepository
        self._session.delete(instance)

        try:
            self._session.flush()
        except IntegrityError:
            raise TopicIdViolatesNotNullRepository

    def list(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[TopicRepositoryDTO], int]:
        """
        Get paginated list of topics from database

        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return
            search: Search string for topic names
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction (True for ascending)

        Returns:
            Tuple of (list of TopicRepositoryDTO, total count after filtering)
        """
        query = self._session.query(Topic)

        if search:
            query = query.filter(Topic.name.ilike(f"%{search}%"))

        filtered_count = query.count()

        if sort_columns and is_sort_ascendings:
            order_criteria = []
            for i, sort_column in enumerate(sort_columns):
                if sort_column and hasattr(Topic, sort_column):
                    attr = getattr(Topic, sort_column)
                    order_criteria.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_criteria:
                query = query.order_by(*order_criteria)

        query = query.offset(offset).limit(limit)

        return [TopicRepositoryDTO.model_validate(r) for r in query.all()], filtered_count

    def get_by_subject(
        self,
        subject_id: int,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
    ) -> tuple[builtins.list[TopicRepositoryDTO], int]:
        """
        Get topics for a specific subject with pagination

        Args:
            subject_id: ID of the subject
            offset: Number of records to skip
            limit: Maximum number of records to return
            search: Search string for topic names
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction (True for ascending)

        Returns:
            Tuple of (list of TopicRepositoryDTO, total count after filtering)
        """
        query = self._session.query(Topic).filter(Topic.subject_id == subject_id)

        if search:
            query = query.filter(Topic.name.ilike(f"%{search}%"))

        filtered_count = query.count()

        if sort_columns and is_sort_ascendings:
            order_criteria = []
            for i, sort_column in enumerate(sort_columns):
                if sort_column and hasattr(Topic, sort_column):
                    attr = getattr(Topic, sort_column)
                    order_criteria.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_criteria:
                query = query.order_by(*order_criteria)

        query = query.offset(offset).limit(limit)

        return [TopicRepositoryDTO.model_validate(r) for r in query.all()], filtered_count

    def get_by_name_and_subject(self, name: str, subject_id: int) -> TopicRepositoryDTO:
        """
        Get topic by name and subject ID

        Args:
            name: Name of the topic
            subject_id: ID of the subject

        Returns:
            TopicRepositoryDTO

        Raises:
            TopicNotFoundRepository: If topic with given name and subject doesn't exist
        """
        instance = (
            self._session.execute(select(Topic).where(Topic.name == name, Topic.subject_id == subject_id))
            .scalars()
            .one_or_none()
        )

        if instance is None:
            raise TopicNotFoundRepository(f"Topic '{name}' not found in subject {subject_id}")

        return TopicRepositoryDTO.model_validate(instance)

    def count_questions(self, topic_id: int) -> int:
        """
        Count number of questions in a topic

        Args:
            topic_id: ID of the topic

        Returns:
            Number of questions
        """
        from quiz.models.edu_content import Question

        return self._session.query(Question).filter_by(topic_id=topic_id).count()

    def get_with_question_counts(self) -> builtins.list[tuple[TopicRepositoryDTO, int]]:
        """
        Get all topics with their question counts

        Returns:
            List of tuples (TopicRepositoryDTO, question_count)
        """
        from quiz.models.edu_content import Question

        query = (
            self._session.query(Topic, func.count(Question.id))
            .outerjoin(Question, Topic.id == Question.topic_id)
            .group_by(Topic.id)
        )

        result = []
        for topic, question_count in query.all():
            result.append((TopicRepositoryDTO.model_validate(topic), question_count))
        return result

    def get_by_subject_with_stats(self, subject_id: int) -> builtins.list[tuple[TopicRepositoryDTO, int]]:
        """
        Get topics for a subject with question count statistics

        Args:
            subject_id: ID of the subject

        Returns:
            List of tuples (TopicRepositoryDTO, question_count)
        """
        from quiz.models.edu_content import Question

        query = (
            self._session.query(Topic, func.count(Question.id))
            .outerjoin(Question, Topic.id == Question.topic_id)
            .filter(Topic.subject_id == subject_id)
            .group_by(Topic.id)
        )

        result = []
        for topic, question_count in query.all():
            result.append((TopicRepositoryDTO.model_validate(topic), question_count))
        return result

    # def get_id_by_name(self, name: str) -> int:
    #     """
    #     Get topic ID by name

    #     Args:
    #         name: Topic name

    #     Returns:
    #         Topic ID

    #     Raises:
    #         TopicNotFoundRepository: If topic with given name doesn't exist
    #     """
    #     instance = self._session.execute(select(Topic).where(Topic.name == name)).scalars().first()

    #     if instance is None:
    #         raise TopicNotFoundRepository

    #     return instance.id

    def get_by_subject_id(self, subject_id: int) -> builtins.list[TopicRepositoryDTO]:
        """
        Get all topics for a specific subject

        Args:
            subject_id: ID of the subject

        Returns:
            List of TopicRepositoryDTO
        """
        topics = self._session.query(Topic).filter(Topic.subject_id == subject_id).all()
        return [TopicRepositoryDTO.model_validate(topic) for topic in topics]

    def get_all_topics_with_detailed_counts(
        self,
    ) -> builtins.list[tuple[TopicRepositoryDTO, int, int]]:
        """Все темы с количеством вопросов и тренажёров за 1 запрос"""
        # Подзапрос для количества вопросов
        question_count_subq = (
            select(Question.topic_id, func.count(Question.id).label("question_count"))
            .group_by(Question.topic_id)
            .subquery()
        )

        # Подзапрос для количества тренажёров
        trainer_count_subq = (
            select(Trainer.topic_id, func.count(Trainer.id).label("trainer_count"))
            .group_by(Trainer.topic_id)
            .subquery()
        )

        stmt = (
            select(
                Topic,
                func.coalesce(question_count_subq.c.question_count, 0).label("question_count"),
                func.coalesce(trainer_count_subq.c.trainer_count, 0).label("trainer_count"),
            )
            .select_from(Topic)
            .outerjoin(question_count_subq, Topic.id == question_count_subq.c.topic_id)
            .outerjoin(trainer_count_subq, Topic.id == trainer_count_subq.c.topic_id)
        )

        result = self._session.execute(stmt).all()

        return [
            (
                TopicRepositoryDTO(id=topic.id, name=topic.name, subject_id=topic.subject_id),
                question_count,
                trainer_count,
            )
            for topic, question_count, trainer_count in result
        ]

    # def get_by_ids(self, topic_ids: builtins.list[int]) -> builtins.list[Topic]:
    #     return self._session.query(Topic).filter(Topic.id.in_(topic_ids)).all()
