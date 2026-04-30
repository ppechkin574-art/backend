import logging
from typing import Protocol

from quiz.converters import to_question_service
from quiz.dtos.admin import AdminTrainerDTO
from quiz.dtos.questions import QuestionServiceDTO
from quiz.dtos.trainers import (
    TrainerCreateServiceDTO,
    TrainerRepositoryDTO,
    TrainerServiceDTO,
    TrainerUpdateServiceDTO,
    TrainerWithQuestionsDTO,
)
from quiz.exceptions import QuestionNotFound, TopicNotFound, TrainerNotFound
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger()


class TrainerServiceInterface(Protocol):
    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[TrainerServiceDTO], int, int]:
        raise NotImplementedError

    def get_by_id(self, trainer_id: int) -> TrainerServiceDTO:
        raise NotImplementedError

    def get_trainer_with_questions(self, trainer_id: int) -> TrainerWithQuestionsDTO:
        raise NotImplementedError

    def create(self, trainer_create: TrainerCreateServiceDTO) -> TrainerServiceDTO:
        raise NotImplementedError

    def update(self, trainer_id: int, trainer_update: TrainerUpdateServiceDTO) -> TrainerServiceDTO:
        raise NotImplementedError

    def delete(self, trainer_id: int) -> None:
        raise NotImplementedError

    async def add_question_to_trainer(self, trainer_id: int, question_id: int) -> None:
        raise NotImplementedError

    def remove_question_from_trainer(self, trainer_id: int, question_id: int) -> None:
        raise NotImplementedError

    def get_all_trainers_with_question_counts(
        self,
    ) -> list[tuple[TrainerServiceDTO, int]]:
        """Получить все тренажёры с количеством вопросов"""
        raise NotImplementedError

    def get_all_trainers(self) -> list[TrainerServiceDTO]:
        """Получить все тренажёры"""
        raise NotImplementedError

    async def get_questions_by_trainer(self, trainer_id: int) -> list[QuestionServiceDTO]:
        """Get questions by trainer ID"""
        raise NotImplementedError

    async def get_or_create_trainer_for_topic(self, topic_id: int, trainer_name: str) -> TrainerServiceDTO:
        """Get or create trainer for topic"""
        raise NotImplementedError

    def get_trainers_by_topic_id(self, topic_id: int) -> list[TrainerServiceDTO]:
        """Get trainers by topic ID"""
        raise NotImplementedError

    def count_questions_by_trainer(self, trainer_id: int) -> int:
        """Count questions in trainer"""
        raise NotImplementedError


class TrainerService:
    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="trainers_list")
    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[TrainerServiceDTO], int, int]:
        """
        Get paginated list of trainers with filtering and sorting

        Args:
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for trainer names
            sort_columns: List of columns to sort by
            is_sort_ascendings: List of boolean flags for sort direction

        Returns:
            Tuple of (list of TrainerServiceDTO, total count, filtered count)
        """
        with self._uow:
            all_trainers = self._uow.trainers.get_all_trainers()

            filtered_trainers = all_trainers
            if search:
                search_lower = search.lower()
                filtered_trainers = [trainer for trainer in all_trainers if search_lower in trainer.name.lower()]

            filtered_count = len(filtered_trainers)
            total_count = len(all_trainers)

            if sort_columns and is_sort_ascendings:
                for i, sort_column in enumerate(reversed(sort_columns)):
                    if i < len(is_sort_ascendings):
                        reverse = not is_sort_ascendings[i]
                        if hasattr(TrainerRepositoryDTO, sort_column):
                            filtered_trainers.sort(key=lambda x: getattr(x, sort_column), reverse=reverse)
            else:
                filtered_trainers.sort(key=lambda x: x.id, reverse=True)

            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_trainers = filtered_trainers[start_index:end_index]

            trainer_dtos = [
                TrainerServiceDTO(
                    id=trainer.id,
                    guid=trainer.guid,
                    name=trainer.name,
                    topic_id=trainer.topic_id,
                )
                for trainer in paginated_trainers
            ]

            return trainer_dtos, total_count, filtered_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="trainer")
    def get_by_id(self, trainer_id: int) -> TrainerServiceDTO:
        """Get trainer by ID"""
        with self._uow:
            trainer_repo_dto = self._uow.trainers.get_by_id(trainer_id)
            if not trainer_repo_dto:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            return TrainerServiceDTO(
                id=trainer_repo_dto.id,
                guid=trainer_repo_dto.guid,
                name=trainer_repo_dto.name,
                topic_id=trainer_repo_dto.topic_id,
            )

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="trainer_with_questions")
    def get_trainer_with_questions(self, trainer_id: int) -> TrainerWithQuestionsDTO:
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            questions = self._uow.trainers.get_questions_by_trainer(trainer_id)
            return TrainerWithQuestionsDTO(
                id=trainer.id,
                name=trainer.name,
                topic_id=trainer.topic_id,
                questions=questions,
            )

    def create(self, trainer_create: TrainerCreateServiceDTO) -> TrainerServiceDTO:
        with self._uow:
            topic = self._uow.topics.get_by_id(trainer_create.topic_id)
            if not topic:
                raise TopicNotFound(f"Topic with id {trainer_create.topic_id} not found")

            trainer_repo_dto = self._uow.trainers.create(trainer_create)
            self._uow.commit()
            self._invalidate_trainer_cache()
            logger.info("Invalidated trainers cache after creation")

            return TrainerServiceDTO(
                id=trainer_repo_dto.id,
                guid=trainer_repo_dto.guid,
                name=trainer_repo_dto.name,
                topic_id=trainer_repo_dto.topic_id,
            )

    def update(self, trainer_id: int, trainer_update: TrainerUpdateServiceDTO) -> TrainerServiceDTO:
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            if trainer_update.topic_id and trainer_update.topic_id != trainer.topic_id:
                topic = self._uow.topics.get_by_id(trainer_update.topic_id)
                if not topic:
                    raise TopicNotFound(f"Topic with id {trainer_update.topic_id} not found")

            updated_trainer = self._uow.trainers.update(trainer_id, trainer_update)
            self._uow.commit()
            self._invalidate_trainer_cache(trainer_id)
            logger.info("Invalidated trainer cache after update")
            return TrainerServiceDTO(
                id=updated_trainer.id,
                guid=updated_trainer.guid,
                name=updated_trainer.name,
                topic_id=updated_trainer.topic_id,
            )

    def delete(self, trainer_id: int) -> None:
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            self._uow.trainers.delete(trainer_id)
            self._uow.commit()
            self._invalidate_trainer_cache(trainer_id)
            logger.info("Invalidated trainer cache after deletion")

    async def add_question_to_trainer(self, trainer_id: int, question_id: int) -> None:
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            question = self._uow.questions.get_by_id(question_id)
            if not question:
                raise QuestionNotFound(f"Question with id {question_id} not found")

            existing_relations = self._uow.trainers.get_trainer_questions(trainer_id)
            if any(r.id == question_id for r in existing_relations):
                logger.info(
                    "Question %s already in trainer %s, skipping",
                    question_id,
                    trainer_id,
                )
                return

            self._uow.trainers.add_question_to_trainer(trainer_id, question_id)
            self._uow.commit()
            logger.info("Successfully added question %s to trainer %s", question_id, trainer_id)
            self._invalidate_trainer_cache(trainer_id)
            logger.info("Invalidated trainer cache after adding question")

    def remove_question_from_trainer(self, trainer_id: int, question_id: int) -> None:
        with self._uow:
            trainer = self._uow.trainers.get_by_id(trainer_id)
            if not trainer:
                raise TrainerNotFound(f"Trainer with id {trainer_id} not found")

            self._uow.trainers.remove_question_from_trainer(trainer_id, question_id)
            self._uow.commit()
            self._invalidate_trainer_cache(trainer_id)
            logger.info("Invalidated trainer cache after removing question")

    # @cached(
    #     strategy=CacheStrategy.GLOBAL,
    #     ttl=604800,
    #     resource="all_trainers_with_question_counts",
    # )
    def get_all_trainers_with_question_counts(
        self,
    ) -> list[tuple[TrainerServiceDTO, int]]:
        """Получить все тренажёры с количеством вопросов"""
        with self._uow:
            trainers_with_counts = self._uow.trainers.get_all_trainers_with_question_counts()
            return [
                (
                    TrainerServiceDTO(
                        id=trainer.id,
                        guid=trainer.guid,
                        name=trainer.name,
                        topic_id=trainer.topic_id,
                    ),
                    count,
                )
                for trainer, count in trainers_with_counts
            ]

    # @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="all_trainers")
    def get_all_trainers(self) -> list[TrainerServiceDTO]:
        """Получить все тренажёры"""
        with self._uow:
            trainers = self._uow.trainers.get_all_trainers()
            return [
                TrainerServiceDTO(
                    id=trainer.id,
                    guid=trainer.guid,
                    name=trainer.name,
                    topic_id=trainer.topic_id,
                )
                for trainer in trainers
            ]

    async def get_or_create_trainer_for_topic(self, topic_id: int, trainer_name: str) -> TrainerServiceDTO:
        """
        Get or create trainer for topic

        Args:
            topic_id: ID of the topic
            trainer_name: Name of the trainer

        Returns:
            TrainerServiceDTO
        """
        with self._uow:
            trainer_repo_dto = self._uow.trainers.get_or_create_by_topic(topic_id, trainer_name)
            return TrainerServiceDTO(
                id=trainer_repo_dto.id,
                guid=trainer_repo_dto.guid,
                name=trainer_repo_dto.name,
                topic_id=trainer_repo_dto.topic_id,
            )

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="trainers_by_topic")
    def get_trainers_by_topic_id(self, topic_id: int) -> list[TrainerServiceDTO]:
        """Get trainers by topic ID"""
        with self._uow:
            trainer_repo_dtos = self._uow.trainers.get_trainers_by_topic_id(topic_id)
            return [
                TrainerServiceDTO(
                    id=trainer.id,
                    guid=trainer.guid,
                    name=trainer.name,
                    topic_id=trainer.topic_id,
                )
                for trainer in trainer_repo_dtos
            ]

    def count_questions_by_trainer(self, trainer_id: int) -> int:
        """Count questions in trainer"""
        with self._uow:
            return self._uow.trainers.count_questions_by_trainer(trainer_id)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_by_trainer")
    async def get_questions_by_trainer(self, trainer_id: int) -> list[QuestionServiceDTO]:
        """Get questions by trainer ID"""
        with self._uow:
            questions_repo = self._uow.trainers.get_questions_by_trainer(trainer_id)
            return [to_question_service(q) for q in questions_repo]

    @cached(
        strategy=CacheStrategy.GLOBAL,
        ttl=604800,
        resource="all_trainers_with_detailed_info",
    )
    def get_all_trainers_with_detailed_info(self) -> list[AdminTrainerDTO]:
        """Получить все тренажёры с детальной информацией для админки"""
        with self._uow:
            trainers_with_counts = self._uow.trainers.get_all_trainers_with_detailed_counts()

            result = []
            for trainer, question_count in trainers_with_counts:
                result.append(
                    AdminTrainerDTO(
                        id=trainer.id,
                        guid=trainer.guid,
                        name=trainer.name,
                        topic_id=trainer.topic_id,
                        question_count=question_count,
                    )
                )

            return result

    def _invalidate_trainer_cache(self, trainer_id: int | None = None):
        """Инвалидировать кеш тренажеров"""
        resources = [
            "trainers_list",
            "trainer",
            "trainer_with_questions",
            "all_trainers_with_question_counts",
            "all_trainers",
            "trainers_by_topic",
            "questions_by_trainer",
            "all_trainers_with_detailed_info",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if trainer_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="trainer",
                    params=f"id:{trainer_id}",
                )
            )

        logger.info("Invalidated trainer cache, deleted %s keys", deleted)
