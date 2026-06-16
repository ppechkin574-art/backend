import builtins
import logging
from typing import Any

from quiz.converters import (
    to_topic_create_repository,
    to_topic_service,
    to_topic_update_repository,
)
from quiz.dtos.admin import AdminTopicDTO
from quiz.dtos.questions import QuestionUpdateRepositoryDTO
from quiz.dtos.topic import (
    TopicCreateServiceDTO,
    TopicServiceDTO,
    TopicUpdateServiceDTO,
)
from quiz.exceptions import (
    TopicIdViolatesNotNullRepository,
    TopicIdViolatesNotNullService,
    TopicNotFoundRepository,
    TopicNotFoundService,
    TopicSameNameRepository,
    TopicSameNameService,
    TopicsMergeError,
    TopicSubjectNotFoundRepository,
    TopicSubjectNotFoundService,
)
from quiz.services.base import BaseServiceInterface
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger()


class TopicServiceInterface(BaseServiceInterface[TopicCreateServiceDTO, TopicUpdateServiceDTO, TopicServiceDTO]):
    """Interface for topic management operations"""

    def get_by_subject(
        self,
        subject_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[TopicServiceDTO], int]:
        """
        Get topics for a specific subject with pagination

        Args:
            subject_id: ID of the subject
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for topic names
            sort_by: Column to sort by
            sort_order: Sort order ('asc' or 'desc')

        Returns:
            Tuple of (list of TopicServiceDTO, total count)
        """
        raise NotImplementedError

    def get_with_question_counts(self) -> list[dict[str, Any]]:
        """
        Get all topics with their question counts

        Returns:
            List of dictionaries containing topic and question_count
        """
        raise NotImplementedError

    def get_by_subject_with_stats(self, subject_id: int) -> list[dict[str, Any]]:
        """
        Get topics for a subject with question count statistics

        Args:
            subject_id: ID of the subject

        Returns:
            List of dictionaries containing topic and question_count
        """
        raise NotImplementedError

    def count_questions(self, topic_id: int) -> int:
        """
        Count number of questions in a topic

        Args:
            topic_id: ID of the topic

        Returns:
            Number of questions

        Raises:
            TopicNotFoundService: If topic with given ID doesn't exist
        """
        raise NotImplementedError

    async def get_or_create_topic(self, name: str, subject_id: int) -> TopicServiceDTO:
        """Get or create topic by name and subject"""
        raise NotImplementedError

    # def get_topic_id_by_name(self, name: str, subject_id: int) -> int:
    #     """Find topic_id by topic name and subject"""
    #     raise NotImplementedError


class TopicService(TopicServiceInterface):
    """Implementation of topic management service"""

    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service

    def _invalidate_topic_cache(self, topic_id: int | None = None, subject_id: int | None = None):
        """Invalidate topic cache"""
        resources = [
            "topics",
            "topic",
            "topics_by_subject",
            "topics_with_question_counts",
            "topics_by_subject_with_stats",
            "topic_question_count",
            "admin_topics",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if topic_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="topic",
                    params=f"id:{topic_id}",
                )
            )

        if subject_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="topics_by_subject",
                    params=f"subject_id:{subject_id}",
                )
            )

        logger.info("Invalidated topic cache, deleted %s keys", deleted)

    def create(self, create_dto: TopicCreateServiceDTO) -> TopicServiceDTO:
        """
        Create a new topic

        Args:
            create_dto: Data for topic creation

        Returns:
            Created TopicServiceDTO

        Raises:
            TopicSameNameService: If topic with same name already exists in subject
            TopicSubjectNotFoundService: If specified subject doesn't exist
        """
        with self._uow:
            try:
                created_topic = self._uow.topics.create(to_topic_create_repository(create_dto))
                self._uow.commit()
                self._invalidate_topic_cache(subject_id=create_dto.subject_id)
                logger.info("Invalidated topics cache after creation")
                return to_topic_service(created_topic)
            except TopicSameNameRepository:
                raise TopicSameNameService
            except TopicSubjectNotFoundRepository:
                raise TopicSubjectNotFoundService

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="topic")
    def get_by_id(self, topic_id: int) -> TopicServiceDTO:
        """
        Get topic by ID

        Args:
            topic_id: ID of the topic

        Returns:
            TopicServiceDTO

        Raises:
            TopicNotFoundService: If topic with given ID doesn't exist
        """
        with self._uow:
            try:
                topic = self._uow.topics.get_by_id(topic_id)
                return to_topic_service(topic)
            except TopicNotFoundRepository:
                raise TopicNotFoundService

    def update(self, topic_id: int, update_dto: TopicUpdateServiceDTO) -> TopicServiceDTO:
        """
        Update topic by ID

        Args:
            topic_id: ID of the topic to update
            update_dto: Data for topic update

        Returns:
            Updated TopicServiceDTO

        Raises:
            TopicNotFoundService: If topic with given ID doesn't exist
            TopicSameNameService: If update would create duplicate topic name in subject
            TopicSubjectNotFoundService: If specified subject doesn't exist
        """
        with self._uow:
            try:
                updated_topic = self._uow.topics.update(topic_id, to_topic_update_repository(update_dto))
                self._uow.commit()
                topic = self._uow.topics.get_by_id(topic_id)
                self._invalidate_topic_cache(topic_id, topic.subject_id)
                logger.info("Invalidated topic cache after update")
                return to_topic_service(updated_topic)
            except TopicNotFoundRepository:
                raise TopicNotFoundService
            except TopicSameNameRepository as e:
                raise TopicSameNameService(
                    f"Topic '{update_dto.name}' already exists in subject",
                    existing_topic_id=e.existing_topic_id,
                )
            except TopicSubjectNotFoundRepository as e:
                raise TopicSubjectNotFoundService(e)

    def delete(self, topic_id: int) -> None:
        """
        Delete topic by ID

        Args:
            topic_id: ID of the topic to delete

        Raises:
            TopicNotFoundService: If topic with given ID doesn't exist
            TopicIdViolatesNotNullService: If topic cannot be deleted due to foreign key constraints
        """
        with self._uow:
            try:
                self._uow.topics.delete(topic_id)
                self._uow.commit()
                topic = self._uow.topics.get_by_id(topic_id)
                subject_id = topic.subject_id
                self._invalidate_topic_cache(topic_id, subject_id)
                logger.info("Invalidated topic cache after deletion")
            except TopicNotFoundRepository:
                raise TopicNotFoundService
            except TopicIdViolatesNotNullRepository:
                raise TopicIdViolatesNotNullService

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="topics")
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[TopicServiceDTO], int]:
        """
        Get paginated list of topics with filtering and sorting

        Args:
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for topic names
            sort_by: Column to sort by
            sort_order: Sort order ('asc' or 'desc')

        Returns:
            Tuple of (list of TopicServiceDTO, total count)
        """
        with self._uow:
            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            topics, total_count = self._uow.topics.list(offset, page_size, search, sort_columns, is_sort_ascendings)

            return [to_topic_service(topic) for topic in topics], total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="topics_by_subject")
    def get_by_subject(
        self,
        subject_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[builtins.list[TopicServiceDTO], int]:
        """
        Get topics for a specific subject with pagination

        Args:
            subject_id: ID of the subject
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for topic names
            sort_by: Column to sort by
            sort_order: Sort order ('asc' or 'desc')

        Returns:
            Tuple of (list of TopicServiceDTO, total count)
        """
        with self._uow:
            self._uow.subjects.get_by_id(subject_id)

            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            topics, total_count = self._uow.topics.get_by_subject(
                subject_id, offset, page_size, search, sort_columns, is_sort_ascendings
            )

            return [to_topic_service(topic) for topic in topics], total_count

    # @cached(
    #     strategy=CacheStrategy.GLOBAL,
    #     ttl=604800,
    #     resource="topics_with_question_counts",
    # )
    def get_with_question_counts(self) -> builtins.list[dict[str, Any]]:
        """
        Get all topics with their question counts

        Returns:
            List of dictionaries containing topic and question_count
        """
        with self._uow:
            topics_with_counts = self._uow.topics.get_with_question_counts()
            return [{"topic": to_topic_service(topic), "question_count": count} for topic, count in topics_with_counts]

    @cached(
        strategy=CacheStrategy.GLOBAL,
        ttl=604800,
        resource="topics_by_subject_with_stats",
    )
    def get_by_subject_with_stats(self, subject_id: int) -> builtins.list[dict[str, Any]]:
        """
        Get topics for a subject with question count statistics

        Args:
            subject_id: ID of the subject

        Returns:
            List of dictionaries containing topic and question_count
        """
        with self._uow:
            topics_with_counts = self._uow.topics.get_by_subject_with_stats(subject_id)
            return [{"topic": to_topic_service(topic), "question_count": count} for topic, count in topics_with_counts]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="topic_question_count")
    def count_questions(self, topic_id: int) -> int:
        """
        Count number of questions in a topic

        Args:
            topic_id: ID of the topic

        Returns:
            Number of questions

        Raises:
            TopicNotFoundService: If topic with given ID doesn't exist
        """
        with self._uow:
            self._uow.topics.get_by_id(topic_id)
            return self._uow.topics.count_questions(topic_id)

    async def get_or_create_topic(self, name: str, subject_id: int) -> TopicServiceDTO:
        """Get or create topic by name and subject"""
        with self._uow:
            try:
                topic_repo_dto = self._uow.topics.get_by_name_and_subject(name, subject_id)
                return to_topic_service(topic_repo_dto)
            except TopicNotFoundRepository:
                try:
                    topic_create_dto = TopicCreateServiceDTO(name=name, subject_id=subject_id)
                    created_topic = self.create(topic_create_dto)
                    return created_topic
                except Exception as e:
                    logger.exception("Error creating topic %s: %s", name, str(e))
                    raise

    # def get_topic_id_by_name(self, name: str, subject_id: int) -> int:
    #     """Find topic_id by topic name and subject"""
    #     with self._uow:
    #         try:
    #             topic = self._uow.topics.get_by_name_and_subject(name, subject_id)
    #             return topic.id
    #         except TopicNotFoundRepository as e:
    #             raise TopicNotFound(f"Topic '{name}' not found in subject {subject_id}") from e

    def merge_topics(self, source_topic_id: int, target_topic_id: int) -> TopicServiceDTO:
        """
        Merge two topics, moving all questions from source to target

        Args:
            source_topic_id: ID of source topic (to merge from)
            target_topic_id: ID of target topic (to merge into)

        Returns:
            Updated TopicServiceDTO of target topic

        Raises:
            TopicNotFoundService: If one of topics doesn't exist
        """
        with self._uow:
            try:
                source_topic = self._uow.topics.get_by_id(source_topic_id)
                target_topic = self._uow.topics.get_by_id(target_topic_id)

                if not source_topic:
                    raise TopicNotFoundService(f"Source topic {source_topic_id} not found")
                if not target_topic:
                    raise TopicNotFoundService(f"Target topic {target_topic_id} not found")
                if source_topic_id == target_topic_id:
                    raise TopicsMergeError("Cannot merge topic with itself")
                if source_topic.subject_id != target_topic.subject_id:
                    raise TopicsMergeError(
                        f"Cannot merge topics from different subjects. "
                        f"Source topic subject_id: {source_topic.subject_id}, "
                        f"Target topic subject_id: {target_topic.subject_id}"
                    )

                logger.info(
                    "Merging topics: %s (%s) -> %s (%s)",
                    source_topic_id,
                    source_topic.name,
                    target_topic_id,
                    target_topic.name,
                )

                source_questions = self._uow.questions.get_by_topic_id(source_topic_id)
                moved_question_ids = []

                for question in source_questions:
                    question_update = QuestionUpdateRepositoryDTO(
                        topic_id=target_topic_id,
                        subject_id=target_topic.subject_id,
                    )
                    self._uow.questions.update(question.id, question_update)
                    moved_question_ids.append(question.id)

                logger.info(
                    "Moved %s questions from topic %s to %s",
                    len(moved_question_ids),
                    source_topic_id,
                    target_topic_id,
                )

                target_trainer = self._uow.trainers.get_by_topic_id(target_topic_id)
                if target_trainer and moved_question_ids:
                    for question_id in moved_question_ids:
                        if not self._uow.trainers.has_question(target_trainer.id, question_id):
                            self._uow.trainers.add_question_to_trainer(target_trainer.id, question_id)

                    logger.info(
                        "Added %s questions to target trainer %s",
                        len(moved_question_ids),
                        target_trainer.id,
                    )

                source_trainer = self._uow.trainers.get_by_topic_id(source_topic_id)
                if source_trainer:
                    try:
                        self._uow.trainers.delete(source_trainer.id)
                        logger.info(
                            "Deleted source trainer %s for topic %s",
                            source_trainer.id,
                            source_topic_id,
                        )
                    except Exception as e:
                        logger.exception("Failed to delete trainer %s: %s", source_trainer.id, str(e))
                        raise
                else:
                    logger.info("No trainer found for source topic %s", source_topic_id)

                try:
                    self._uow.topics.delete(source_topic_id)
                    logger.info("Deleted source topic %s", source_topic_id)
                except Exception as e:
                    logger.exception("Failed to delete topic %s: %s", source_topic_id, str(e))
                    raise

                self._uow.commit()

                if hasattr(self._uow, "session"):
                    self._uow.session.expire_all()

                source_topic = self._uow.topics.get_by_id(source_topic_id)
                target_topic = self._uow.topics.get_by_id(target_topic_id)

                self._invalidate_topic_cache(source_topic_id, source_topic.subject_id)
                self._invalidate_topic_cache(target_topic_id, target_topic.subject_id)
                logger.info("Invalidated topics cache after merge")

                updated_target = self._uow.topics.get_by_id(target_topic_id)
                return to_topic_service(updated_target)

            except TopicNotFoundRepository as e:
                self._uow.rollback()
                raise TopicNotFoundService(str(e))
            except Exception as e:
                self._uow.rollback()
                logger.exception(
                    "Error merging topics %s -> %s: %s",
                    source_topic_id,
                    target_topic_id,
                    str(e),
                )
                raise

    def get_all_topics_with_detailed_info(self) -> builtins.list[AdminTopicDTO]:
        """Получить все темы с детальной информацией для админки"""
        with self._uow:
            question_counts = self._uow.questions.count_all_by_topic()
            trainer_counts = self._uow.trainers.count_all_by_topic()
            topics_with_counts = self._uow.topics.get_all_topics_with_detailed_counts()

            result = []
            for topic, _question_count, _trainer_count in topics_with_counts:
                result.append(
                    AdminTopicDTO(
                        id=topic.id,
                        name=topic.name,
                        subject_id=topic.subject_id,
                        question_count=question_counts.get(topic.id, 0),
                        trainer_count=trainer_counts.get(topic.id, 0),
                        trainers=[],
                    )
                )
            return result

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="topic_progress")
    def get_topic_progress(self, topic_id: int, user_id: str, only_correct: bool = True) -> float:
        """Получить прогресс по теме как число от 0 до 1"""
        with self._uow:
            return self._uow.progress.get_topic_progress(user_id, topic_id, only_correct)
