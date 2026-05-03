import logging
from typing import Protocol
from uuid import UUID

from quiz.converters import to_ent_option_get_repo, to_service_question
from quiz.dtos.admin import AdminEntOptionDTO
from quiz.dtos.ent_attempts import EntAttemptOptionStatisticServiceDTO
from quiz.dtos.ent_options import (
    EntOptionCreateServiceDTO,
    EntOptionsGetServiceDTO,
    EntOptionsServiceDTO,
    EntOptionUpdateServiceDTO,
    EntOptionWithQuestionsDTO,
)
from quiz.dtos.questions import QuestionServiceDTO
from quiz.exceptions import (
    EntOptionsDoesntExist,
    QuestionNotFound,
    SubjectNotFound,
)
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class EntOptionServiceInterface(Protocol):
    def get_ents(self, option_params_dto: EntOptionsGetServiceDTO) -> list[EntOptionsServiceDTO]:
        raise NotImplementedError

    def get_ent_questions(self, ent_option_id: int) -> list[QuestionServiceDTO]:
        raise NotImplementedError

    def get_by_id(self, ent_option_id: int) -> EntOptionsServiceDTO:
        raise NotImplementedError

    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[EntOptionsServiceDTO], int, int]:
        raise NotImplementedError

    def get_ent_with_questions(self, ent_option_id: int) -> EntOptionWithQuestionsDTO:
        raise NotImplementedError

    def create(self, ent_create: EntOptionCreateServiceDTO) -> EntOptionsServiceDTO:
        raise NotImplementedError

    def update(self, ent_option_id: int, ent_update: EntOptionUpdateServiceDTO) -> EntOptionsServiceDTO:
        raise NotImplementedError

    def delete(self, ent_option_id: int) -> None:
        raise NotImplementedError

    def add_question_to_ent(self, ent_option_id: int, question_id: int) -> None:
        raise NotImplementedError

    def remove_question_from_ent(self, ent_option_id: int, question_id: int) -> None:
        raise NotImplementedError

    def get_all_ent_options(
        self, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[EntOptionsServiceDTO], int]:
        raise NotImplementedError

    def get_option_by_number(self, option_number: int) -> EntOptionsServiceDTO | None:
        raise NotImplementedError

    def get_count_by_subject(self, subject_id: int) -> int:
        raise NotImplementedError

    def get_next_option_number(self, subject_id: int) -> int:
        raise NotImplementedError

    # def get_options_by_question_id(self, question_id: int) -> list[EntOptionsServiceDTO]:
    #     raise NotImplementedError

    def add_questions_to_option(self, ent_option_id: int, question_ids: list[int]) -> None:
        raise NotImplementedError

    def remove_questions_from_option(self, ent_option_id: int, question_ids: list[int]) -> None:
        raise NotImplementedError

    def get_ent_questions_count(self, ent_option_id: int) -> int:
        raise NotImplementedError

    def check_question_in_ent_option(self, ent_option_id: int, question_id: int) -> bool:
        raise NotImplementedError


class EntOptionService:
    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service

    def _to_service_dto(self, option, include_best_attempt: bool = True) -> EntOptionsServiceDTO:
        """Универсальный метод преобразования в DTO"""
        best_attempt_service = None
        if include_best_attempt and hasattr(option, "best_attempt") and option.best_attempt:
            best_attempt_service = EntAttemptOptionStatisticServiceDTO(
                attempt_id=option.best_attempt.attempt_id,
                score=option.best_attempt.score,
                skiped=option.best_attempt.skiped,
                correct=option.best_attempt.correct,
                partial_correct=option.best_attempt.partial_correct,
                incorrect=option.best_attempt.incorrect,
                spend_time=option.best_attempt.spend_time,
            )

        return EntOptionsServiceDTO(
            id=option.id,
            subject=option.subject,
            subject_id=option.subject_id,
            option_number=option.option_number,
            best_attempt=best_attempt_service,
        )

    def _invalidate_ent_cache(self, ent_option_id: int | None = None, user_id: UUID | None = None):
        """Invalidate all options cache"""
        resources = [
            "ent_options",
            "ent_questions",
            "ent_option",
            "ent_with_questions",
            "ent_options_by_subject",
            "ent_options_count",
            "ent_options_with_counts",
            "ent_questions_count",
            "question_in_option",
            "ent_option_by_number",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources, user_id)

        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="ent_options_with_counts",
                params="",
            )
        )

        if ent_option_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="ent_option",
                    params=f"id:{ent_option_id}",
                )
            )

            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="ent_with_questions",
                    params=f"id:{ent_option_id}",
                )
            )

        logger.info("Invalidated ENT cache, deleted %s keys", deleted)

    @cached(strategy=CacheStrategy.USER, ttl=604800, resource="ent_options")
    def get_ents(self, option_params_dto: EntOptionsGetServiceDTO) -> list[EntOptionsServiceDTO]:
        """Get ENT options for user"""
        logger.info("Getting ENT options for user %s", option_params_dto.student_guid)
        with self._uow:
            option_params_repo = to_ent_option_get_repo(option_params_dto)
            result = self._uow.ent_options.get_ent_options(option_params_repo)
            if not result:
                raise EntOptionsDoesntExist("ENT options not found")

            options = [self._to_service_dto(option) for option in result]
            logger.info(
                "Retrieved %s ENT options from DB for user %s",
                len(options),
                option_params_dto.student_guid,
            )
            return options

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_questions")
    def get_ent_questions(self, ent_option_id: int) -> list[QuestionServiceDTO]:
        """Get questions of option"""
        logger.info("Getting ENT questions for option %s", ent_option_id)

        with self._uow:
            questions_repo = self._uow.ent_options.get_option_questions(ent_option_id)
            questions = [to_service_question(q) for q in questions_repo]
            logger.info(
                "Retrieved %s questions for ENT option %s",
                len(questions),
                ent_option_id,
            )
            return questions

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_option")
    def get_by_id(self, ent_option_id: int) -> EntOptionsServiceDTO:
        """Get option by ID"""
        logger.info("Getting ENT option by ID: %s", ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")
            return self._to_service_dto(option)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_with_questions")
    def get_ent_with_questions(self, ent_option_id: int) -> EntOptionWithQuestionsDTO:
        """Get option with questions"""
        logger.info("Getting ENT option with questions: %s", ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            questions = self._uow.ent_options.get_questions_by_ent_option(ent_option_id)
            return EntOptionWithQuestionsDTO(
                id=option.id,
                option_number=option.option_number,
                subject_id=option.subject_id,
                questions=questions,
            )

    def list_query(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[EntOptionsServiceDTO], int, int]:
        """Get options list with pagination"""
        logger.info("Listing ENT options, page %s, size %s", page, page_size)

        with self._uow:
            return self._uow.ent_options.list_query(page, page_size, search, sort_columns, is_sort_ascendings)

    def create(self, ent_create: EntOptionCreateServiceDTO) -> EntOptionsServiceDTO:
        """Create option"""
        logger.info("Creating ENT option for subject %s", ent_create.subject_id)

        with self._uow:
            subject = self._uow.subjects.get_by_id(ent_create.subject_id)
            if not subject:
                raise SubjectNotFound(f"Subject with id {ent_create.subject_id} not found")

            if ent_create.option_number is None:
                ent_create.option_number = self.get_next_option_number(ent_create.subject_id)

            option = self._uow.ent_options.create(ent_create)
            self._uow.commit()

            self._invalidate_ent_cache()
            logger.info("Invalidated ENT options cache after creation")

            created_option = self._uow.ent_options.get_by_id(option.id)
            return self._to_service_dto(created_option)

    def update(self, ent_option_id: int, ent_update: EntOptionUpdateServiceDTO) -> EntOptionsServiceDTO:
        """Update option with invalidate existed cache"""
        logger.info("Updating ENT option %s", ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            if ent_update.subject_id and ent_update.subject_id != option.subject_id:
                subject = self._uow.subjects.get_by_id(ent_update.subject_id)
                if not subject:
                    raise SubjectNotFound(f"Subject with id {ent_update.subject_id} not found")

            updated_option = self._uow.ent_options.update(ent_option_id, ent_update)
            self._uow.commit()

            self._invalidate_ent_cache()
            logger.info("Invalidated ENT options cache after creation")

            return self._to_service_dto(updated_option)

    def delete(self, ent_option_id: int) -> None:
        """Delete option with invalidate existed cache"""
        logger.info("Deleting ENT option %s", ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            self._uow.ent_options.delete(ent_option_id)
            self._uow.commit()

            self._cache_service.invalidate_by_resource("ent_options")
            self._cache_service.invalidate_by_resource("ent_option")
            self._cache_service.invalidate_by_resource("ent_options_list")
            self._cache_service.invalidate_by_resource("ent_options_admin")
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="ent_option",
                    params=f"id:{ent_option_id}",
                )
            )
            logger.info("Invalidated ENT options cache after deletion")

    def add_question_to_ent(self, ent_option_id: int, question_id: int) -> None:
        """Add question to option with invalidate existed cache"""
        logger.info("Adding question %s to ENT option %s", question_id, ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            question = self._uow.questions.get_by_id(question_id)
            if not question:
                raise QuestionNotFound(f"Question with id {question_id} not found")

            self._uow.ent_options.add_question_to_ent(ent_option_id, question_id)
            self._uow.commit()

            self._cache_service.invalidate_by_resource("ent_questions")
            self._cache_service.invalidate_by_resource("ent_with_questions")
            self._cache_service.invalidate_by_resource("ent_options_admin")
            logger.info("Invalidated ENT questions cache after adding question")

    def remove_question_from_ent(self, ent_option_id: int, question_id: int) -> None:
        """Delete question from option with invalidate existed cache"""
        logger.info("Removing question %s from ENT option %s", question_id, ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            self._uow.ent_options.remove_question_from_ent(ent_option_id, question_id)
            self._uow.commit()

            self._cache_service.invalidate_by_resource("ent_questions")
            self._cache_service.invalidate_by_resource("ent_with_questions")
            self._cache_service.invalidate_by_resource("ent_options_admin")
            logger.info("Invalidated ENT questions cache after removing question")

    def get_all_ent_options(
        self, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[EntOptionsServiceDTO], int]:
        """Get all options"""
        logger.info("Getting all ENT options for admin, page %s, size %s", page, page_size)

        with self._uow:
            options, total_count = self._uow.ent_options.get_all_ent_options(page, page_size, search)
            return [self._to_service_dto(option, include_best_attempt=False) for option in options], total_count

    @cached(
        strategy=CacheStrategy.GLOBAL,
        ttl=604800,
        resource="ent_option_by_subject_and_number",
    )
    def get_by_subject_and_number(self, subject_id: int, option_number: int) -> EntOptionsServiceDTO | None:
        """Get option by subject and number"""
        logger.info("Getting ENT option by subject %s and number %s", subject_id, option_number)

        with self._uow:
            option = self._uow.ent_options.get_by_subject_and_number(subject_id, option_number)
            if option:
                return self._to_service_dto(option, include_best_attempt=False)
            return None

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_options_count")
    def get_count_by_subject(self, subject_id: int) -> int:
        """Get count of options for subject"""
        logger.info("Getting ENT options count for subject %s", subject_id)

        with self._uow:
            try:
                count = self._uow.ent_options.get_count_by_subject(subject_id)
                logger.info("Found %s ENT options for subject %s", count, subject_id)
                return count
            except Exception as e:
                logger.exception(
                    "Error getting ENT options count for subject %s: %s",
                    subject_id,
                    str(e),
                )
                return 0

    def get_next_option_number(self, subject_id: int) -> int:
        """Получить следующий доступный номер варианта для предмета"""
        logger.info("Getting next option number for subject %s", subject_id)

        with self._uow:
            try:
                max_number = self._uow.ent_options.get_max_option_number_for_subject(subject_id)
                return (max_number or 0) + 1
            except Exception as e:
                logger.exception("Error getting next option number: %s", str(e))
                return 1

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_options_by_subject")
    def get_by_subject(self, subject_id: int) -> list[EntOptionsServiceDTO]:
        """Get all options for subject"""
        logger.info("Getting ENT options for subject %s", subject_id)

        with self._uow:
            options = self._uow.ent_options.get_by_subject_id(subject_id)
            return [EntOptionsServiceDTO.model_validate(option) for option in options]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_options_with_counts")
    def get_all_ent_options_with_counts(self) -> list[AdminEntOptionDTO]:
        """Get all options with question count"""
        logger.info("Getting ENT options with counts")

        with self._uow:
            try:
                options_with_counts = self._uow.ent_options.get_all_ent_options_with_question_counts()
                result = []
                for option, question_count in options_with_counts:
                    result.append(
                        AdminEntOptionDTO(
                            id=option.id,
                            option_number=option.option_number,
                            subject_id=option.subject_id,
                            subject_name=option.subject.name,
                            question_count=question_count,
                        )
                    )
                return result
            except Exception as e:
                logger.exception("Error getting ENT options with counts: %s", str(e))
                return self._get_simplified_ent_options()

    def _get_simplified_ent_options(self) -> list[AdminEntOptionDTO]:
        """Simplified method to get option (fallback)"""
        try:
            options, _ = self._uow.ent_options.get_all_ent_options(1, 1000)
            return [
                AdminEntOptionDTO(
                    id=option.id,
                    option_number=option.option_number,
                    subject_id=option.subject_id,
                    subject_name=option.subject,
                    question_count=0,
                )
                for option in options
            ]
        except Exception as e:
            logger.exception("Error in simplified ENT options: %s", str(e))
            return []

    def get_max_option_number(self) -> int:
        """Get max number of option"""
        logger.info("Getting max ENT option number")

        with self._uow:
            max_number = self._uow.ent_options.get_max_option_number()
            return max_number or 0

    def add_questions_to_option(self, ent_option_id: int, question_ids: list[int]) -> None:
        """Add some questions to option with invalidate cache"""
        logger.info("Adding %s questions to ENT option %s", len(question_ids), ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            for question_id in question_ids:
                question = self._uow.questions.get_by_id(question_id)
                if not question:
                    raise QuestionNotFound(f"Question with id {question_id} not found")

            self._uow.ent_options.bulk_add_questions(ent_option_id, question_ids)
            self._uow.commit()

            self._cache_service.invalidate_by_resource("ent_questions")
            self._cache_service.invalidate_by_resource("ent_with_questions")
            self._cache_service.invalidate_by_resource("ent_options_admin")
            logger.info("Invalidated ENT questions cache after bulk add")

    def remove_questions_from_option(self, ent_option_id: int, question_ids: list[int]) -> None:
        """Delete some questions from option with invalidate cache"""
        logger.info("Removing %s questions from ENT option %s", len(question_ids), ent_option_id)

        with self._uow:
            option = self._uow.ent_options.get_by_id(ent_option_id)
            if not option:
                raise EntOptionsDoesntExist(f"ENT option with id {ent_option_id} not found")

            self._uow.ent_options.bulk_remove_questions(ent_option_id, question_ids)
            self._uow.commit()

            self._cache_service.invalidate_by_resource("ent_questions")
            self._cache_service.invalidate_by_resource("ent_with_questions")
            self._cache_service.invalidate_by_resource("ent_options_admin")
            logger.info("Invalidated ENT questions cache after bulk remove")

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_questions_count")
    def get_questions_count(self, ent_option_id: int) -> int:
        """Get question count in option"""
        logger.info("Getting questions count for ENT option %s", ent_option_id)

        with self._uow:
            return self._uow.ent_options.count_questions_by_option(ent_option_id)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question_in_option")
    def check_question_in_option(self, ent_option_id: int, question_id: int) -> bool:
        """Check if question exist in option"""
        logger.info("Checking if question %s is in ENT option %s", question_id, ent_option_id)

        with self._uow:
            return self._uow.ent_options.check_question_in_option(ent_option_id, question_id)
