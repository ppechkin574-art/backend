import logging

from quiz.dtos.ent_questions import (
    EntOptionQuestionCreateDTO,
    EntOptionQuestionServiceDTO,
)
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class EntOptionQuestionServiceInterface:
    def __init__(self, _uow: UnitOfWorkTests, _cache_service: CacheService):
        raise ValueError("Invalid initialization")


class EntOptionQuestionService:
    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self.uow = uow
        self._cache_service = cache_service

    def create(self, create_dto: EntOptionQuestionCreateDTO) -> EntOptionQuestionServiceDTO:
        """Создать связь между ENT вариантом и вопросом"""
        repo_dto = self.uow.ent_questions.create(create_dto)
        self._invalidate_ent_question_cache(create_dto.ent_option_id, create_dto.question_id)
        return EntOptionQuestionServiceDTO.model_validate(repo_dto)

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="ent_option_questions")
    def get_by_ent_option_id(self, ent_option_id: int) -> list[EntOptionQuestionServiceDTO]:
        """Получить все связи по ID ENT варианта"""
        repo_dtos = self.uow.ent_questions.get_by_ent_option_id(ent_option_id)
        return [EntOptionQuestionServiceDTO.model_validate(dto) for dto in repo_dtos]

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question_ent_options")
    def get_by_question_id(self, question_id: int) -> list[EntOptionQuestionServiceDTO]:
        """Получить все связи по ID вопроса"""
        repo_dtos = self.uow.ent_questions.get_by_question_id(question_id)
        return [EntOptionQuestionServiceDTO.model_validate(dto) for dto in repo_dtos]

    def find_duplicate_ent_option(self, question_ids: list[int], subject_id: int) -> int | None:
        """
        Найти ENT вариант с точно таким же набором вопросов.
        Возвращает ID ENT варианта или None.
        """
        try:
            return self.uow.ent_questions.find_ent_option_with_questions(question_ids, subject_id)
        except Exception as e:
            logger.exception("Error finding duplicate ENT option: %s", str(e))
            return None

    @cached(strategy=CacheStrategy.GLOBAL, ttl=604800, resource="question_in_ent_option")
    def is_question_in_any_ent_option(self, question_id: int) -> bool:
        """Проверяет, находится ли вопрос в любом ЕНТ варианте"""
        try:
            ent_questions = self.get_by_question_id(question_id)
            return len(ent_questions) > 0
        except Exception as e:
            logger.exception(
                "Error checking if question %s is in any ENT option: %s",
                question_id,
                str(e),
            )
            return False

    # def are_questions_in_any_ent_option(self, question_ids: list[int]) -> dict[int, bool]:
    #     """Проверяет, находятся ли вопросы в любых ЕНТ вариантах"""
    #     result = {}
    #     try:
    #         for question_id in question_ids:
    #             result[question_id] = self.is_question_in_any_ent_option(question_id)
    #         return result
    #     except Exception as e:
    #         logger.exception("Error checking questions in ENT options: %s", str(e))
    #         return dict.fromkeys(question_ids, False)

    def _invalidate_ent_question_cache(self, ent_option_id: int, question_id: int):
        """Инвалидировать кеши связей вопросов ЕНТ"""
        resources = [
            "ent_option_questions",
            "question_ent_options",
            "question_in_ent_option",
        ]

        self._cache_service.invalidate_by_resources(resources)

        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="ent_option_questions",
                params=f"id:{ent_option_id}",
            )
        )

        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="question_ent_options",
                params=f"id:{question_id}",
            )
        )

        self._cache_service.delete(
            self._cache_service.make_key(
                CacheStrategy.GLOBAL,
                resource="question_in_ent_option",
                params=f"id:{question_id}",
            )
        )

        logger.info(
            "Invalidated ENT question cache for option %s, question %s",
            ent_option_id,
            question_id,
        )
