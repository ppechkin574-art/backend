import builtins
import logging
from typing import Any

from fastapi import UploadFile

from quiz.converters import (
    to_subject_create_repository,
    to_subject_service,
    to_subject_update_repository,
    to_topic_service,
)
from quiz.dtos.admin import AdminSubjectDTO
from quiz.dtos.ent_options import EntOptionUpdateDTO
from quiz.dtos.ent_questions import EntQuestionsUpdateDTO
from quiz.dtos.progress import SubjectProgressDTO, TopicProgressDTO
from quiz.dtos.questions import QuestionUpdateRepositoryDTO
from quiz.dtos.subject import (
    SubjectCreateServiceDTO,
    SubjectServiceDTO,
    SubjectUpdateServiceDTO,
)
from quiz.dtos.topic import TopicServiceDTO, TopicUpdateRepositoryDTO
from quiz.exceptions import (
    SubjectIdViolatesNotNullRepository,
    SubjectIdViolatesNotNullService,
    SubjectIntegrityErrorRepository,
    SubjectIntegrityErrorService,
    SubjectNotFoundRepository,
    SubjectNotFoundService,
    SubjectSameNameRepository,
    SubjectSameNameService,
)
from quiz.services.base import BaseServiceInterface
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached
from utils.file_service import FileService

logger = logging.getLogger()


class SubjectServiceInterface(
    BaseServiceInterface[SubjectCreateServiceDTO, SubjectUpdateServiceDTO, SubjectServiceDTO]
):
    """Interface for subject management operations"""

    def get_topics(self, subject_id: int) -> list[TopicServiceDTO]:
        """
        Get all topics for a specific subject

        Args:
            subject_id: ID of the subject

        Returns:
            List of TopicServiceDTO objects

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        raise NotImplementedError

    async def get_or_create_by_name(self, name: str) -> SubjectServiceDTO:
        """
        Get existing subject by name or create new one

        Args:
            name: Name of the subject

        Returns:
            SubjectServiceDTO (existing or newly created)
        """
        raise NotImplementedError

    def get_with_topic_counts(self) -> list[dict[str, Any]]:
        """
        Get all subjects with their topic counts

        Returns:
            List of dictionaries containing subject and topic_count
        """
        raise NotImplementedError

    def get_with_question_counts(self) -> list[dict[str, Any]]:
        """
        Get all subjects with their question counts

        Returns:
            List of dictionaries containing subject and question_count
        """
        raise NotImplementedError

    def get_detailed_stats(self, subject_id: int) -> dict[str, Any]:
        """
        Get detailed statistics for a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Dictionary with subject details, topic count, question count, and topics list

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        raise NotImplementedError

    def count_topics(self, subject_id: int) -> int:
        """
        Count number of topics in a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Number of topics

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        raise NotImplementedError

    def merge_subjects(self, source_subject_id: int, target_subject_id: int) -> SubjectServiceDTO:
        """
        Merge two subjects, moving all topics and questions from source to target

        Args:
            source_subject_id: ID of source subject (to merge from)
            target_subject_id: ID of target subject (to merge into)

        Returns:
            Updated SubjectServiceDTO of target subject

        Raises:
            SubjectNotFoundService: If one of subjects doesn't exist
        """
        raise NotImplementedError


class SubjectService(SubjectServiceInterface):
    def __init__(
        self,
        uow: UnitOfWorkTests,
        file_service: FileService,
        cache_service: CacheService,
    ):
        self._uow = uow
        self._file_service = file_service
        self._cache_service = cache_service

    def _invalidate_subject_cache(self, subject_id: int | None = None):
        """Invalidate subject cache"""
        resources = [
            "subjects",
            "subject",
            "subject_topics",
            "subject_with_topic_counts",
            "subject_with_question_counts",
            "subject_detailed_stats",
            "subject_topic_count",
            "admin_subjects",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if subject_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="subject",
                    params=f"id:{subject_id}",
                )
            )

        logger.info("Invalidated subject cache, deleted %s keys", deleted)

    def create(self, create_dto: SubjectCreateServiceDTO) -> SubjectServiceDTO:
        """
        Create a new subject

        Args:
            create_dto: Data for subject creation

        Returns:
            Created SubjectServiceDTO

        Raises:
            SubjectIntegrityErrorService: If subject creation violates integrity constraints
        """
        with self._uow:
            try:
                created_subject = self._uow.subjects.create(to_subject_create_repository(create_dto))
                self._uow.commit()
                self._invalidate_subject_cache()
                logger.info("Invalidated subjects cache after creation")
                return to_subject_service(created_subject, self._file_service)
            except SubjectIntegrityErrorRepository:
                raise SubjectIntegrityErrorService

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject")
    def get_by_id(self, subject_id: int) -> SubjectServiceDTO:
        """
        Get subject by ID

        Args:
            subject_id: ID of the subject

        Returns:
            SubjectServiceDTO

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        with self._uow:
            try:
                return to_subject_service(self._uow.subjects.get_by_id(subject_id), self._file_service)
            except SubjectNotFoundRepository:
                raise SubjectNotFoundService

    def update(self, subject_id: int, update_dto: SubjectUpdateServiceDTO) -> SubjectServiceDTO:
        """
        Update subject by ID

        Args:
            subject_id: ID of the subject to update
            update_dto: Data for subject update

        Returns:
            Updated SubjectServiceDTO

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
            SubjectIntegrityErrorService: If update violates integrity constraints
        """
        with self._uow:
            try:
                updated_subject = self._uow.subjects.update(subject_id, to_subject_update_repository(update_dto))
                self._uow.commit()
                self._invalidate_subject_cache(subject_id)
                logger.info("Invalidated subject cache after update")
                return to_subject_service(updated_subject, self._file_service)
            except SubjectNotFoundRepository:
                raise SubjectNotFoundService
            except SubjectSameNameRepository as e:
                raise SubjectSameNameService(
                    f"Subject '{update_dto.name}' already exists",
                    existing_subject_id=e.existing_subject_id,
                )
            except SubjectIntegrityErrorRepository as e:
                raise SubjectIntegrityErrorService(e)

    def delete(self, subject_id: int) -> None:
        """
        Delete subject by ID

        Args:
            subject_id: ID of the subject to delete

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
            SubjectIdViolatesNotNullService: If subject cannot be deleted due to foreign key constraints
        """
        with self._uow:
            try:
                self._uow.subjects.delete(subject_id)
                self._uow.commit()
                self._invalidate_subject_cache(subject_id)
                logger.info("Invalidated subject cache after deletion")
            except SubjectNotFoundRepository:
                raise SubjectNotFoundService
            except SubjectIdViolatesNotNullRepository:
                raise SubjectIdViolatesNotNullService

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subjects")
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[SubjectServiceDTO], int]:
        """
        Get paginated list of subjects with filtering and sorting

        Args:
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for subject names
            sort_by: Column to sort by
            sort_order: Sort order ('asc' or 'desc')

        Returns:
            Tuple of (list of SubjectServiceDTO, total count)
        """
        with self._uow:
            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            subjects, total_count = self._uow.subjects.list(offset, page_size, search, sort_columns, is_sort_ascendings)

            return [to_subject_service(subject, self._file_service) for subject in subjects], total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_topics")
    def get_topics(self, subject_id: int) -> builtins.list[TopicServiceDTO]:
        """
        Get all topics for a specific subject

        Args:
            subject_id: ID of the subject

        Returns:
            List of TopicServiceDTO objects

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        with self._uow:
            return [to_topic_service(topic) for topic in (self._uow.subjects.get_by_id(subject_id)).topics]

    async def get_or_create_by_name(self, name: str) -> SubjectServiceDTO:
        """
        Get existing subject by name or create new one

        Args:
            name: Name of the subject

        Returns:
            SubjectServiceDTO (existing or newly created)
        """
        with self._uow:
            try:
                return to_subject_service(self._uow.subjects.get_by_name(name), self._file_service)
            except SubjectNotFoundRepository:
                return self.create(SubjectCreateServiceDTO(name=name))

    # @cached(
    #     strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_with_topic_counts"
    # )
    def get_with_topic_counts(self) -> builtins.list[dict[str, Any]]:
        """
        Get all subjects with their topic counts

        Returns:
            List of dictionaries containing subject and topic_count
        """
        with self._uow:
            return [
                {"subject": to_subject_service(subject, self._file_service), "topic_count": count}
                for subject, count in self._uow.subjects.get_with_topic_counts()
            ]

    # @cached(
    #     strategy=CacheStrategy.GLOBAL,
    #     ttl=604800,
    #     resource="subject_with_question_counts",
    # )
    def get_with_question_counts(self) -> builtins.list[dict[str, Any]]:
        """
        Get all subjects with their question counts

        Returns:
            List of dictionaries containing subject and question_count
        """
        with self._uow:
            return [
                {"subject": to_subject_service(subject, self._file_service), "question_count": count}
                for subject, count in self._uow.subjects.get_with_question_counts()
            ]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_detailed_stats")
    def get_detailed_stats(self, subject_id: int) -> dict[str, Any]:
        """
        Get detailed statistics for a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Dictionary with subject details, topic count, question count, and topics list

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        with self._uow:
            subject = self._uow.subjects.get_by_id(subject_id)
            return {
                "subject": to_subject_service(subject, self._file_service),
                "topic_count": self.count_topics(subject_id),
                "question_count": self._uow.questions.count_by_subject(subject_id),
                "topics": [to_topic_service(topic) for topic in subject.topics],
            }

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="subject_topic_count")
    def count_topics(self, subject_id: int) -> int:
        """
        Count number of topics in a subject

        Args:
            subject_id: ID of the subject

        Returns:
            Number of topics

        Raises:
            SubjectNotFoundService: If subject with given ID doesn't exist
        """
        with self._uow:
            return self._uow.subjects.count_topics(subject_id)

    def merge_subjects(self, source_subject_id: int, target_subject_id: int) -> SubjectServiceDTO:
        """
        Merge two subjects, moving all topics and questions from source to target

        Args:
            source_subject_id: ID of source subject (to merge from)
            target_subject_id: ID of target subject (to merge into)

        Returns:
            Updated SubjectServiceDTO of target subject

        Raises:
            SubjectNotFoundService: If one of subjects doesn't exist
        """
        with self._uow:
            try:
                source_topics = self._uow.topics.get_by_subject_id(source_subject_id)
                for topic in source_topics:
                    topic_update = TopicUpdateRepositoryDTO(subject_id=target_subject_id)
                    self._uow.topics.update(topic.id, topic_update)

                all_source_questions = self._uow.questions.get_questions_by_subject(source_subject_id)
                for question in all_source_questions:
                    question_update = QuestionUpdateRepositoryDTO(subject_id=target_subject_id)
                    self._uow.questions.update(question.id, question_update)

                try:
                    source_ent_options = self._uow.ent_options.get_by_subject_id(source_subject_id)
                    for ent_option in source_ent_options:
                        ent_option_update = EntOptionUpdateDTO(subject_id=target_subject_id)
                        self._uow.ent_options.update(ent_option.id, ent_option_update)
                except Exception as e:
                    logger.warning("Could not move ENT options: %s", str(e))

                try:
                    all_ent_questions = (
                        self._uow.ent_questions.list(0, 10000)[0] if hasattr(self._uow.ent_questions, "list") else []
                    )
                    for ent_question in all_ent_questions:
                        question = self._uow.questions.get_by_id(ent_question.question_id)
                        if question and question.subject_id == source_subject_id:
                            ent_question_update = EntQuestionsUpdateDTO(subject_id=target_subject_id)
                            self._uow.ent_questions.update(ent_question.id, ent_question_update)

                except Exception as e:
                    logger.warning("Could not update ENT questions: %s", str(e))

                self._uow.subjects.delete(source_subject_id)
                logger.info("Deleted source subject %s", source_subject_id)
                self._uow.commit()
                return to_subject_service(self._uow.subjects.get_by_id(target_subject_id), self._file_service)

            except SubjectNotFoundRepository as e:
                raise SubjectNotFoundService(str(e))
            except Exception as e:
                self._uow.rollback()
                logger.exception(
                    "Error merging subjects %s -> %s: %s",
                    source_subject_id,
                    target_subject_id,
                    str(e),
                )
                raise

    # def _get_questions_without_topic_by_subject(self, subject_id: int):
    #     # This logic can be implemented in question repository
    #     # For now using simple approach through existing methods
    #     return [
    #         q
    #         for q in self._uow.questions.list(0, 10000)[0]
    #         if q.subject_id == subject_id and (not hasattr(q, "topic_id") or q.topic_id is None)
    #     ]

    def get_all_subjects_with_detailed_info(self) -> builtins.list[AdminSubjectDTO]:
        with self._uow:
            result = []
            for (
                subject,
                topic_count,
                _,
            ) in self._uow.subjects.get_all_subjects_with_detailed_counts():
                accurate_question_count = self._uow.questions.count_by_subject(subject.id)

                result.append(
                    AdminSubjectDTO(
                        id=subject.id,
                        name=subject.name,
                        type=subject.type,
                        image=self._file_service.get_subject_image_url(subject.image),
                        topic_count=topic_count,
                        question_count=accurate_question_count,
                        topics=[],
                    )
                )
            return result

    async def upload_subject_image(self, image_file: UploadFile) -> str:
        return await self._file_service.save_subject_image(image_file)

    def delete_subject_image(self, image_url: str) -> bool:
        if image_url:
            return self._file_service.delete_subject_image(image_url.split("/")[-1])
        return False

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="subject_progress")
    def get_subject_progress(self, subject_id: int, user_id: str, only_correct: bool = True) -> float:
        with self._uow:
            return self._uow.progress.get_subject_progress(user_id, subject_id, only_correct)

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="subjects_with_progress")
    def get_subjects_with_progress(self, user_id: str, only_correct: bool = True) -> builtins.list[SubjectProgressDTO]:
        with self._uow:
            result = []
            for subject_data in self._uow.progress.get_subjects_with_progress(user_id, only_correct):
                image = subject_data.get("image")
                subject_data["image"] = self._file_service.get_subject_image_url(image) if image else None
                result.append(SubjectProgressDTO(**subject_data))

            return result

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="topics_with_progress")
    def get_topics_with_progress(
        self, subject_id: int, user_id: str, only_correct: bool = True
    ) -> builtins.list[TopicProgressDTO]:
        with self._uow:
            self._uow.subjects.get_by_id(subject_id)
            result = []
            for topic_data in self._uow.progress.get_topics_with_progress_by_subject(user_id, subject_id, only_correct):
                result.append(TopicProgressDTO(**topic_data))

            return result

    def count_questions_by_subject(self, subject_id: int) -> int:
        with self._uow:
            return self._uow.questions.count_by_subject(subject_id)
