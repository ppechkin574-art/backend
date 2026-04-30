import builtins

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quiz.dtos import SubjectCreateRepositoryDTO, SubjectRepositoryDTO
from quiz.dtos.subject import SubjectUpdateRepositoryDTO
from quiz.exceptions import (
    SubjectIdViolatesNotNullRepository,
    SubjectIntegrityErrorRepository,
    SubjectNotFoundRepository,
    SubjectSameNameRepository,
)
from quiz.models.edu_content import Question, Subject, Topic
from quiz.services.base import BaseRepositoryInterface


class SubjectRepositoryInterface(
    BaseRepositoryInterface[SubjectCreateRepositoryDTO, SubjectUpdateRepositoryDTO, SubjectRepositoryDTO]
):
    """Interface for subject data access operations"""

    def get_by_name(self, name: str) -> SubjectRepositoryDTO:
        """
        Get subject by name

        Args:
            name: Name of the subject

        Returns:
            SubjectRepositoryDTO

        Raises:
            SubjectNotFoundRepository: If subject with given name doesn't exist
        """
        raise NotImplementedError

    def get_or_create_by_name(self, name: str) -> SubjectRepositoryDTO:
        """
        Get existing subject by name or create new one

        Args:
            name: Name of the subject

        Returns:
            SubjectRepositoryDTO (existing or newly created)
        """
        raise NotImplementedError

    def count_topics(self, subject_id: int) -> int:
        """
        Count number of topics in a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Number of topics
        """
        raise NotImplementedError

    def get_with_topic_counts(self) -> list[tuple[SubjectRepositoryDTO, int]]:
        """
        Get all subjects with their topic counts

        Returns:
            List of tuples (SubjectRepositoryDTO, topic_count)
        """
        raise NotImplementedError

    def get_with_question_counts(self) -> list[tuple[SubjectRepositoryDTO, int]]:
        """
        Get all subjects with their question counts

        Returns:
            List of tuples (SubjectRepositoryDTO, question_count)
        """
        raise NotImplementedError


class SubjectRepository(SubjectRepositoryInterface):
    """Implementation of subject data access operations"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: SubjectCreateRepositoryDTO) -> SubjectRepositoryDTO:
        """
        Create a new subject in database

        Args:
            create_dto: Data for subject creation

        Returns:
            Created SubjectRepositoryDTO

        Raises:
            SubjectIntegrityErrorRepository: If subject creation violates integrity constraints
        """
        instance = Subject(**create_dto.model_dump())
        self._session.add(instance)

        try:
            self._session.flush()
            return SubjectRepositoryDTO.model_validate(instance)
        except IntegrityError:
            raise SubjectIntegrityErrorRepository

    def get_by_id(self, subject_id: int) -> SubjectRepositoryDTO:
        """
        Get subject by ID from database

        Args:
            subject_id: ID of the subject

        Returns:
            SubjectRepositoryDTO

        Raises:
            SubjectNotFoundRepository: If subject with given ID doesn't exist
        """
        instance = self._session.get(Subject, subject_id)
        if instance is None:
            raise SubjectNotFoundRepository
        return SubjectRepositoryDTO.model_validate(instance)

    def update(self, subject_id: int, update_dto: SubjectUpdateRepositoryDTO) -> SubjectRepositoryDTO:
        """
        Update subject by ID in database

        Args:
            subject_id: ID of the subject to update
            update_dto: Data for subject update

        Returns:
            Updated SubjectRepositoryDTO

        Raises:
            SubjectNotFoundRepository: If subject with given ID doesn't exist
            SubjectIntegrityErrorRepository: If update violates integrity constraints
        """
        instance = self._session.get(Subject, subject_id)
        if instance is None:
            raise SubjectNotFoundRepository

        update_data = update_dto.model_dump(exclude_unset=True)

        if "name" in update_data:
            name = update_data["name"]
            existing_subject = (
                self._session.execute(select(Subject).where(Subject.name == name, Subject.id != subject_id))
                .scalars()
                .first()
            )

            if existing_subject:
                raise SubjectSameNameRepository(
                    f"Subject '{name}' already exists",
                    existing_subject_id=existing_subject.id,
                )

        for key, value in update_data.items():
            setattr(instance, key, value)

        try:
            self._session.flush()
            return SubjectRepositoryDTO.model_validate(instance)
        except IntegrityError as e:
            raise SubjectIntegrityErrorRepository(e)

    def delete(self, subject_id: int) -> None:
        """
        Delete subject by ID from database

        Args:
            subject_id: ID of the subject to delete

        Raises:
            SubjectNotFoundRepository: If subject with given ID doesn't exist
            SubjectIdViolatesNotNullRepository: If subject cannot be deleted due to foreign key constraints
        """
        instance = self._session.get(Subject, subject_id)
        if instance is None:
            raise SubjectNotFoundRepository
        self._session.delete(instance)

        try:
            self._session.flush()
        except IntegrityError:
            raise SubjectIdViolatesNotNullRepository

    def list(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[SubjectRepositoryDTO], int]:
        """
        Get paginated list of subjects from database

        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return
            search: Search string for subject names
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction (True for ascending)

        Returns:
            Tuple of (list of SubjectRepositoryDTO, total count after filtering)
        """
        query = self._session.query(Subject)

        if search:
            query = query.filter(Subject.name.ilike(f"%{search}%"))

        filtered_count = query.count()

        if sort_columns and is_sort_ascendings:
            order_criteria = []
            for i, sort_column in enumerate(sort_columns):
                if sort_column and hasattr(Subject, sort_column):
                    attr = getattr(Subject, sort_column)
                    order_criteria.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_criteria:
                query = query.order_by(*order_criteria)

        query = query.offset(offset).limit(limit)

        return [SubjectRepositoryDTO.model_validate(r) for r in query.all()], filtered_count

    def get_by_name(self, name: str) -> SubjectRepositoryDTO:
        """
        Get subject by name

        Args:
            name: Name of the subject

        Returns:
            SubjectRepositoryDTO

        Raises:
            SubjectNotFoundRepository: If subject with given name doesn't exist
        """
        instance = self._session.execute(select(Subject).where(Subject.name == name)).scalars().one_or_none()

        if instance is None:
            raise SubjectNotFoundRepository

        return SubjectRepositoryDTO.model_validate(instance)

    def get_or_create_by_name(self, name: str) -> SubjectRepositoryDTO:
        """
        Get existing subject by name or create new one

        Args:
            name: Name of the subject

        Returns:
            SubjectRepositoryDTO (existing or newly created)
        """
        try:
            return self.get_by_name(name)
        except SubjectNotFoundRepository:
            return self.create(SubjectCreateRepositoryDTO(name=name))

    def count_topics(self, subject_id: int) -> int:
        """
        Count number of topics in a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Number of topics
        """
        return self._session.query(Topic).filter_by(subject_id=subject_id).count()

    def get_with_topic_counts(self) -> builtins.list[tuple[SubjectRepositoryDTO, int]]:
        """
        Get all subjects with their topic counts

        Returns:
            List of tuples (SubjectRepositoryDTO, topic_count)
        """
        subjects = self._session.query(Subject).all()
        result = []
        for subject in subjects:
            topic_count = self.count_topics(subject.id)
            result.append((SubjectRepositoryDTO.model_validate(subject), topic_count))
        return result

    def get_with_question_counts(
        self,
    ) -> builtins.list[tuple[SubjectRepositoryDTO, int]]:
        """
        Get all subjects with their question counts

        Returns:
            List of tuples (SubjectRepositoryDTO, question_count)
        """
        from quiz.models.edu_content import Question

        query = (
            self._session.query(Subject, func.count(Question.id))
            .outerjoin(Question, Subject.id == Question.subject_id)
            .group_by(Subject.id)
        )

        result = []
        for subject, question_count in query.all():
            result.append((SubjectRepositoryDTO.model_validate(subject), question_count))
        return result

    def get_all_subjects_with_detailed_counts(
        self,
    ) -> builtins.list[tuple[SubjectRepositoryDTO, int, int]]:
        """Все предметы с количеством тем и вопросов за 1 запрос"""
        topic_count_subq = (
            select(Topic.subject_id, func.count(Topic.id).label("topic_count")).group_by(Topic.subject_id).subquery()
        )

        question_count_subq = (
            select(Topic.subject_id, func.count(Question.id).label("question_count"))
            .join(Question, Topic.id == Question.topic_id)
            .group_by(Topic.subject_id)
            .subquery()
        )

        stmt = (
            select(
                Subject,
                func.coalesce(topic_count_subq.c.topic_count, 0).label("topic_count"),
                func.coalesce(question_count_subq.c.question_count, 0).label("question_count"),
            )
            .select_from(Subject)
            .outerjoin(topic_count_subq, Subject.id == topic_count_subq.c.subject_id)
            .outerjoin(question_count_subq, Subject.id == question_count_subq.c.subject_id)
        )

        result = self._session.execute(stmt).all()

        return [
            (
                SubjectRepositoryDTO(
                    id=subject.id,
                    name=subject.name,
                    topics=[],
                    type=subject.type,
                    image=subject.image,
                ),
                topic_count,
                question_count,
            )
            for subject, topic_count, question_count in result
        ]

    # def get_by_ids(self, subject_ids: builtins.list[int]) -> builtins.list[Subject]:
    #     return self._session.query(Subject).filter(Subject.id.in_(subject_ids)).all()
