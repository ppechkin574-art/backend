import builtins
import logging
import uuid

from quiz.converters import (
    to_question_create_repo,
    to_question_update_repo,
    to_service_question,
)
from quiz.dtos.enums import Difficulty, QuestionType
from quiz.dtos.questions import (
    QuestionCreateServiceDTO,
    QuestionServiceDTO,
    QuestionUpdateServiceDTO,
)
from quiz.exceptions import (
    EntOptionsDoesntExist,
    QuestionNotFound,
    TopicNotFound,
    TopicRepoNotFound,
)
from quiz.services.base import BaseServiceInterface
from quiz.uows.uows import UnitOfWorkQuestions
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger()


class QuestionServiceInterface(
    BaseServiceInterface[QuestionCreateServiceDTO, QuestionUpdateServiceDTO, QuestionServiceDTO]
):
    """Interface for question management operations with unified interface"""

    def get_questions_in_trainers(self) -> list[QuestionServiceDTO]:
        """
        Get all questions that are included in trainers

        Returns:
            List of QuestionServiceDTO
        """
        raise NotImplementedError

    def get_questions_in_ent_options(self) -> list[QuestionServiceDTO]:
        """
        Get all questions that are included in ENT options

        Returns:
            List of QuestionServiceDTO
        """
        raise NotImplementedError

    def get_question_stats_by_subject(self) -> dict[int, int]:
        """
        Get question statistics by subject

        Returns:
            Dictionary with subject_id as key and question count as value
        """
        raise NotImplementedError

    def get_question_stats_by_topic(self) -> dict[int, int]:
        """
        Get question statistics by topic

        Returns:
            Dictionary with topic_id as key and question count as value
        """
        raise NotImplementedError

    def count_questions_by_subject(self, subject_id: int) -> int:
        """
        Count questions by subject

        Args:
            subject_id: ID of the subject

        Returns:
            Number of questions in the subject
        """
        raise NotImplementedError

    def count_questions_by_topic(self, topic_id: int) -> int:
        """
        Count questions by topic

        Args:
            topic_id: ID of the topic

        Returns:
            Number of questions in the topic
        """
        raise NotImplementedError

    # def get_subject_id_by_name(self, name: str) -> int:
    #     """
    #     Find subject_id by subject name

    #     Args:
    #         name: Subject name

    #     Returns:
    #         Subject ID
    #     """
    #     raise NotImplementedError

    def get_trainers_by_subject(self, subject_id: int, student_id: uuid.UUID) -> list[dict]:
        """
        Get trainers by subject with student progress information

        Args:
            subject_id: ID of the subject
            student_id: UUID of the student

        Returns:
            List of dictionaries containing trainers and progress info
        """
        raise NotImplementedError

    # async def get_or_create_subject(self, subject_name: str) -> int:
    #     """
    #     Get or create subject by name

    #     Args:
    #         subject_name: Name of the subject

    #     Returns:
    #         Subject ID
    #     """
    #     raise NotImplementedError

    def get_questions_by_topic(self, topic_id: int) -> list[QuestionServiceDTO]:
        """
        Get questions by topic ID

        Args:
            topic_id: ID of the topic

        Returns:
            List of QuestionServiceDTO
        """
        raise NotImplementedError

    # async def create_question(self, question: QuestionCreateServiceDTO) -> QuestionServiceDTO:
    #     """
    #     Create a new question

    #     Args:
    #         question: Data for question creation

    #     Returns:
    #         Created QuestionServiceDTO
    #     """
    #     raise NotImplementedError

    def get_questions_by_subject(self, subject_id: int) -> list[QuestionServiceDTO]:
        """Получить вопросы по предмету"""
        raise NotImplementedError


class QuestionService(QuestionServiceInterface):
    """Implementation of question management service with unified interface"""

    def __init__(self, uow: UnitOfWorkQuestions, cache_service: CacheService):
        self.uow = uow
        self._cache_service = cache_service

    def create(self, question: QuestionCreateServiceDTO) -> QuestionServiceDTO:
        """
        Create a new question

        Args:
            question: Data for question creation

        Returns:
            Created QuestionServiceDTO

        Raises:
            TopicNotFound: If specified topic doesn't exist
        """
        with self.uow:
            try:
                question_repo = to_question_create_repo(question)
                created_question = self.uow.questions.add(question_repo)
                self.uow.commit()
                self._invalidate_question_cache()
                logger.info("Invalidated questions cache after creation")
                return QuestionServiceDTO.model_validate(created_question)
            except TopicRepoNotFound:
                raise TopicNotFound

    # async def create_question(self, question: QuestionCreateServiceDTO) -> QuestionServiceDTO:
    #     """
    #     Async method to create a new question

    #     Args:
    #         question: Data for question creation

    #     Returns:
    #         Created QuestionServiceDTO
    #     """
    #     return self.create(question)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question")
    def get_by_id(self, question_id: int) -> QuestionServiceDTO:
        """
        Get question by ID

        Args:
            question_id: ID of the question

        Returns:
            QuestionServiceDTO

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
        """
        with self.uow:
            try:
                question = self.uow.questions.get_by_id(question_id)
                return to_service_question(question)
            except QuestionNotFound:
                raise QuestionNotFound

    def update(self, question_id: int, question: QuestionUpdateServiceDTO) -> QuestionServiceDTO:
        """
        Update question by ID

        Args:
            question_id: ID of the question to update
            question: Data for question update

        Returns:
            Updated QuestionServiceDTO

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
            TopicNotFound: If specified topic doesn't exist
        """
        with self.uow:
            try:
                question_update_repo = to_question_update_repo(question)
                updated_question = self.uow.questions.update(question_id, question_update_repo)
                self.uow.commit()
                self._invalidate_question_cache(question_id)
                logger.info("Invalidated question cache after update")
                return QuestionServiceDTO.model_validate(updated_question)
            except QuestionNotFound:
                raise QuestionNotFound
            except TopicRepoNotFound:
                raise TopicNotFound

    def delete(self, question_id: int) -> None:
        """
        Delete question by ID

        Args:
            question_id: ID of the question to delete

        Raises:
            QuestionNotFound: If question with given ID doesn't exist
        """
        with self.uow:
            try:
                self.uow.questions.delete(question_id)
                self.uow.commit()
                self._invalidate_question_cache(question_id)
                logger.info("Invalidated question cache after deletion")
            except QuestionNotFound:
                raise QuestionNotFound

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_list")
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
        difficulty: list[Difficulty] | None = None,
        question_type: list[QuestionType] | None = None,
        subject_ids: list[int] | None = None,
        topic_ids: list[int] | None = None,
        usage_type: str | None = None,
    ) -> tuple[list[QuestionServiceDTO], int]:
        """
        Get paginated list of questions with filtering and sorting

        Args:
            page: Page number (1-based)
            page_size: Number of items per page
            search: Search string for question content
            sort_by: Column to sort by
            sort_order: Sort order ('asc' or 'desc')
            difficulty: Filter by difficulty levels
            question_type: Filter by question types
            subject_ids: Filter by subject IDs
            topic_ids: Filter by topic IDs
            usage_type: Filter by assigned types

        Returns:
            Tuple of (list of QuestionServiceDTO, total count)
        """
        with self.uow:
            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            questions, total_count = self.uow.questions.list_query(
                offset,
                page_size,
                search,
                sort_columns,
                is_sort_ascendings,
                difficulty,
                question_type,
                subject_ids,
                topic_ids,
                usage_type,
            )

            return [to_service_question(question) for question in questions], total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_in_trainers")
    def get_questions_in_trainers(self) -> builtins.list[QuestionServiceDTO]:
        """Get all questions that are included in trainers"""
        with self.uow:
            questions = self.uow.questions.get_questions_in_trainers()
            return [to_service_question(q) for q in questions]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_in_ent_options")
    def get_questions_in_ent_options(self) -> builtins.list[QuestionServiceDTO]:
        """Get all questions that are included in ENT options"""
        with self.uow:
            questions = self.uow.questions.get_questions_in_ent_options()
            return [to_service_question(q) for q in questions]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question_stats_by_subject")
    def get_question_stats_by_subject(self) -> dict[int, int]:
        """Get question statistics by subject"""
        with self.uow:
            stats = self.uow.questions.get_subject_questions_stats()
            return dict(stats)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question_stats_by_topic")
    def get_question_stats_by_topic(self) -> dict[int, int]:
        """Get question statistics by topic"""
        with self.uow:
            stats = self.uow.questions.get_topic_questions_stats()
            return dict(stats)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_count_by_subject")
    def count_questions_by_subject(self, subject_id: int) -> int:
        """Count questions by subject"""
        with self.uow:
            return self.uow.questions.count_by_subject(subject_id)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_count_by_topic")
    def count_questions_by_topic(self, topic_id: int) -> int:
        """Count questions by topic"""
        with self.uow:
            return self.uow.questions.count_by_topic(topic_id)

    # def get_subject_id_by_name(self, name: str) -> int:
    #     """Get subject ID by name"""
    #     with self.uow:
    #         subject_id = self.uow.subjects.get_or_create_by_name(name).id
    #         if not subject_id:
    #             raise TopicNotFound(f"Topic '{name}' not found")
    #         return subject_id

    # @cached(strategy=CacheStrategy.USER, ttl=3600, resource="trainers_by_subject")
    def get_trainers_by_subject(self, subject_id: int, student_id: uuid.UUID) -> builtins.list[dict]:
        """Get trainers by subject with student progress"""
        logger.info(
            "get_trainers_by_subject called with subject_id=%s, student_id=%s",
            subject_id,
            student_id,
        )

        cache_key = f"user:{student_id}:trainers_by_subject:subject_id={subject_id}"
        cached_result = self._cache_service.get(cache_key)
        if cached_result is not None:
            logger.info("Cache hit for %s", cache_key)
            return cached_result

        logger.info("Cache miss for %s, fetching from DB", cache_key)

        with self.uow:
            topics = self.uow.topics.get_by_subject_id(subject_id)
            logger.info("Found %s topics for subject %s", len(topics), subject_id)
            result = []

            for topic in topics:
                trainers = self.uow.trainers.get_trainers_by_topic_id(topic.id)
                logger.info(
                    "Found %s trainers for topic %s (%s)",
                    len(trainers),
                    topic.id,
                    topic.name,
                )
                trainers_info = []

                for trainer in trainers:
                    question_count = self.uow.trainers.count_questions_by_trainer(trainer.id)
                    answered_question_ids = self.uow.questions.get_answered_questions_by_trainer(
                        student_guid=student_id, trainer_id=trainer.id
                    )

                    all_questions = self.uow.questions.get_by_trainer_id(trainer.id)
                    question_id_to_index = {q.id: idx for idx, q in enumerate(all_questions)}
                    completed_indexes = [
                        question_id_to_index[q_id] for q_id in answered_question_ids if q_id in question_id_to_index
                    ]

                    trainers_info.append(
                        {
                            "id": trainer.id,
                            "name": trainer.name,
                            "question_count": question_count,
                            "completed_question_indexes": completed_indexes,
                        }
                    )

                if trainers_info:
                    result.append(
                        {
                            "id": topic.id,
                            "name": topic.name,
                            "subject_id": topic.subject_id,
                            "trainers": trainers_info,
                        }
                    )

            logger.info(
                "Returning %s topics with trainers for subject %s",
                len(result),
                subject_id,
            )
            self._cache_service.set(cache_key, result, ttl=3600)
            return result

    # async def get_or_create_subject(self, subject_name: str) -> int:
    #     """
    #     Get or create subject by name

    #     Args:
    #         subject_name: Name of the subject

    #     Returns:
    #         Subject ID
    #     """
    #     with self.uow:
    #         subject = self.uow.subjects.get_or_create_by_name(subject_name)
    #         return subject.id

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_count_by_topic")
    def get_questions_by_topic(self, topic_id: int) -> builtins.list[QuestionServiceDTO]:
        """Get questions by topic ID"""
        with self.uow:
            questions = self.uow.questions.get_by_topic_id(topic_id)
            return [to_service_question(q) for q in questions]

    # Legacy methods for backward compatibility
    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
        difficulty: builtins.list[Difficulty] | None = None,
        question_type: builtins.list[QuestionType] | None = None,
        subject_ids: builtins.list[int] | None = None,
        topic_ids: builtins.list[int] | None = None,
    ) -> tuple[builtins.list[QuestionServiceDTO], int, int]:
        """
        Legacy method for backward compatibility
        """
        questions, total_count = self.list(
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_columns[0] if sort_columns else None,
            sort_order=("asc" if (is_sort_ascendings and is_sort_ascendings[0]) else "desc"),
            difficulty=difficulty,
            question_type=question_type,
            subject_ids=subject_ids,
            topic_ids=topic_ids,
        )
        return questions, total_count, total_count

    # def update_question(self, question_id: int, question: QuestionUpdateServiceDTO) -> None:
    #     """Legacy update method for backward compatibility"""
    #     self.update(question_id, question)

    def add_question(self, question: QuestionCreateServiceDTO) -> None:
        """Legacy create method for backward compatibility"""
        self.create(question)

    # def create_ent_option(self, ent_option: EntOptionCreateDTO) -> EntOptionsServiceDTO:
    #     """Create ENT option"""
    #     with self.uow:
    #         return self.uow.ent_options.create_option(ent_option)

    def get_option_by_number(self, ent_number: int):
        """Get ENT option by number"""
        with self.uow:
            option = self.uow.ent_options.get_option_by_number(ent_number)
            if option:
                from quiz.dtos.ent_options import EntOptionsServiceDTO

                return EntOptionsServiceDTO.model_validate(option)
            raise EntOptionsDoesntExist

    def import_questions(self, questions: builtins.list[QuestionCreateServiceDTO]) -> None:
        """Import questions in bulk"""
        with self.uow:
            for question in questions:
                self.uow.questions.add(to_question_create_repo(question))
            self._invalidate_question_cache()
            logger.info("Invalidated questions cache after import")

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="questions_by_subject")
    def get_questions_by_subject(self, subject_id: int) -> builtins.list[QuestionServiceDTO]:
        with self.uow:
            questions = self.uow.questions.get_questions_by_subject(subject_id)
            return [to_service_question(q) for q in questions]

    def _invalidate_question_cache(self, question_id: int | None = None):
        """Инвалидировать кеш вопросов"""
        resources = [
            "questions_list",
            "questions_in_trainers",
            "questions_in_ent_options",
            "question_stats_by_subject",
            "question_stats_by_topic",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if question_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="question",
                    params=f"id:{question_id}",
                )
            )

        logger.info("Invalidated question cache, deleted %s keys", deleted)
