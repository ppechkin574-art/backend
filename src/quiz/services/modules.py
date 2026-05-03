import builtins
import logging
from datetime import datetime

# from typing import Any
from uuid import UUID

from quiz.converters import (
    to_module_lesson_repository,
    to_module_lesson_service,
    to_subject_module_repository,
    to_subject_module_service,
    to_subject_module_update_repository,
)
from quiz.dtos.enums import Status
from quiz.dtos.modules import (
    # LessonProgressShortDTO,
    LessonWithTestInfoDTO,
    ModuleInSubjectResponseDTO,
    ModuleLessonCreateServiceDTO,
    # ModuleLessonResponseDTO,
    ModuleLessonServiceDTO,
    ModuleLessonShortDTO,
    ModuleLessonUpdateServiceDTO,
    ModuleLessonWithDetailsDTO,
    ModuleLessonWithTrainerDTO,
    ModuleTestCreateRepositoryDTO,
    ModuleTestCreateServiceDTO,
    ModuleTestServiceDTO,
    ModuleTestUpdateRepositoryDTO,
    ModuleTestUpdateServiceDTO,
    ModuleWithTestInfoDTO,
    SubjectModuleCreateServiceDTO,
    SubjectModuleServiceDTO,
    SubjectModulesResponseDTO,
    SubjectModuleUpdateServiceDTO,
    # SubjectModuleWithLessonsDTO,
    UserLessonProgressDTO,
    UserModuleProgressDTO,
)
from quiz.exceptions import (
    LessonIdViolatesNotNullService,
    LessonIntegrityErrorService,
    LessonNotPublishedError,
    LessonOrderUpdateError,
    LessonSameNameService,
    ModuleIdViolatesNotNullService,
    ModuleIntegrityErrorService,
    ModuleLessonNotFoundService,
    ModuleOrderUpdateError,
    ModuleSameNameService,
    ModuleTestNotFoundService,
    SubjectModuleNotFoundService,
    SubjectNotFoundService,
    TopicNotFoundService,
)
from quiz.services.base import BaseServiceInterface
from quiz.services.cashback import CashbackService
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger()


class SubjectModuleServiceInterface(
    BaseServiceInterface[
        SubjectModuleCreateServiceDTO,
        SubjectModuleUpdateServiceDTO,
        SubjectModuleServiceDTO,
    ]
):
    """Interface for subject module management operations"""

    def get_by_subject(
        self,
        subject_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[SubjectModuleServiceDTO], int]:
        """Get modules by subject ID"""
        raise NotImplementedError

    # def get_with_lessons(
    #     self, module_id: int, user_id: UUID | None = None
    # ) -> SubjectModuleWithLessonsDTO:
    #     """Get module with its lessons and progress"""
    #     raise NotImplementedError

    def count_lessons(self, module_id: int) -> int:
        """Count lessons in module"""
        raise NotImplementedError

    def get_module_progress(self, module_id: int, user_id: UUID) -> UserModuleProgressDTO:
        """Get user progress for module"""
        raise NotImplementedError

    def update_module_progress(
        self,
        module_id: int,
        user_id: UUID,
        lesson_completed: bool = False,
        test_completed: bool = False,
        time_spent: int = 0,
    ) -> UserModuleProgressDTO:
        """Update user progress for module"""
        raise NotImplementedError


class SubjectModuleService(SubjectModuleServiceInterface):
    """Implementation of subject module management service"""

    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service
        # self._lesson_service = ModuleLessonService(uow, cache_service)

    def _invalidate_module_cache(
        self,
        module_id: int | None = None,
        subject_id: int | None = None,
        user_id: UUID | None = None,
    ):
        """Invalidate module cache"""
        resources = [
            "subject_modules",
            "subject_module",
            "modules_by_subject",
            "module_with_lessons",
            "module_lesson_count",
            "module_progress",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if module_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="subject_module",
                    params=f"id:{module_id}",
                )
            )

        if subject_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="modules_by_subject",
                    params=f"subject_id:{subject_id}",
                )
            )

        if user_id and module_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="module_progress",
                    user_id=str(user_id),
                    params=f"module_id:{module_id}",
                )
            )

        logger.info("Invalidated module cache, deleted %s keys", deleted)

    def create(self, create_dto: SubjectModuleCreateServiceDTO) -> SubjectModuleServiceDTO:
        """Create a new subject module"""
        with self._uow:
            try:
                self._uow.subjects.get_by_id(create_dto.subject_id)
                modules, _ = self.get_by_subject(create_dto.subject_id, page_size=1000)
                existing_orders = [m.order_index for m in modules]
                if create_dto.order_index in existing_orders:
                    self._uow.subject_modules.shift_right_for_insert(create_dto.subject_id, create_dto.order_index)

                created_module = self._uow.subject_modules.create(to_subject_module_repository(create_dto))
                self._uow.commit()
                self._invalidate_module_cache(subject_id=create_dto.subject_id)
                logger.info("Created module: %s", created_module.id)
                return to_subject_module_service(created_module)

            except SubjectNotFoundService:
                raise SubjectNotFoundService(f"Subject with id {create_dto.subject_id} not found")
            except ModuleSameNameService as e:
                raise ModuleSameNameService(
                    f"Module '{create_dto.title}' already exists in subject",
                    existing_module_id=e.existing_module_id,
                )
            except ModuleIntegrityErrorService as e:
                raise ModuleIntegrityErrorService(str(e))

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="subject_module")
    def get_by_id(self, module_id: int) -> SubjectModuleServiceDTO:
        """Get module by ID"""
        with self._uow:
            try:
                module = self._uow.subject_modules.get_by_id(module_id)
                return to_subject_module_service(module)
            except SubjectModuleNotFoundService:
                raise SubjectModuleNotFoundService(f"Module with id {module_id} not found")

    def update(self, module_id: int, update_dto: SubjectModuleUpdateServiceDTO) -> SubjectModuleServiceDTO:
        """Update module by ID"""
        with self._uow:
            try:
                module = self._uow.subject_modules.get_by_id(module_id)
                subject_id = module.subject_id
                old_order = module.order_index

                if update_dto.order_index is not None and update_dto.order_index != old_order:
                    self._uow.subject_modules.shift_for_update(subject_id, old_order, update_dto.order_index)
                updated_module = self._uow.subject_modules.update(
                    module_id, to_subject_module_update_repository(update_dto)
                )
                self._uow.commit()
                self._invalidate_module_cache(module_id, module.subject_id)
                logger.info("Updated module: %s", module_id)
                return to_subject_module_service(updated_module)

            except SubjectModuleNotFoundService:
                raise SubjectModuleNotFoundService(f"Module with id {module_id} not found")
            except ModuleSameNameService as e:
                raise ModuleSameNameService("Module name conflict", existing_module_id=e.existing_module_id)
            except ModuleIntegrityErrorService as e:
                raise ModuleIntegrityErrorService(str(e)) from e

    def delete(self, module_id: int) -> None:
        """Delete module by ID and reorder remaining modules in the subject"""
        with self._uow:
            try:
                module = self._uow.subject_modules.get_by_id(module_id)
                subject_id = module.subject_id
                deleted_order = module.order_index

                self._uow.subject_modules.delete(module_id)

                self._uow.subject_modules.reorder_after_delete(subject_id, deleted_order)

                self._uow.commit()
                self._invalidate_module_cache(module_id, subject_id)
                logger.info(
                    "Deleted module: %s and reordered modules in subject %s",
                    module_id,
                    subject_id,
                )

            except SubjectModuleNotFoundService:
                raise SubjectModuleNotFoundService(f"Module with id {module_id} not found")
            except ModuleIdViolatesNotNullService:
                raise ModuleIdViolatesNotNullService(f"Cannot delete module {module_id} due to foreign key constraints")

    # @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="subject_modules")
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[SubjectModuleServiceDTO], int]:
        """Get paginated list of modules"""
        with self._uow:
            # sort_columns = [sort_by] if sort_by else None
            # is_sort_ascendings = [sort_order == "asc"] if sort_by else None
            sort_columns = []
            is_sort_ascendings = []
            if sort_by:
                columns = [c.strip() for c in sort_by.split(",") if c.strip()]
                sort_columns = columns
                # sort_order может быть одним значением или таким же количеством, как колонки
                orders = [s.strip() for s in (sort_order or "").split(",") if s.strip()]
                # Если передан один sort_order, применяем его ко всем колонкам
                if len(orders) == 1:
                    is_sort_ascendings = [orders[0].lower() == "asc"] * len(columns)
                else:
                    # Если передано несколько, то предполагаем, что количество совпадает
                    is_sort_ascendings = [order.lower() == "asc" for order in orders]

            offset = (page - 1) * page_size
            modules, total_count = self._uow.subject_modules.list(
                offset, page_size, search, sort_columns, is_sort_ascendings
            )

            result = [to_subject_module_service(module) for module in modules]
            return result, total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="modules_by_subject")
    def get_by_subject(
        self,
        subject_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[builtins.list[SubjectModuleServiceDTO], int]:
        """Get modules by subject ID"""
        with self._uow:
            self._uow.subjects.get_by_id(subject_id)

            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            modules, total_count = self._uow.subject_modules.get_by_subject(
                subject_id, offset, page_size, search, sort_columns, is_sort_ascendings
            )

            return [to_subject_module_service(module) for module in modules], total_count

    # def get_with_lessons(
    #     self, module_id: int, user_id: UUID | None = None
    # ) -> SubjectModuleWithLessonsDTO:
    #     """Get module with its lessons"""
    #     with self._uow:
    #         module = self._uow.subject_modules.get_by_id(module_id)
    #         module_dto = to_subject_module_service(module)

    #         lessons, _ = self._uow.module_lessons.get_by_module(module_id)
    #         lessons_dto = [to_module_lesson_service(lesson) for lesson in lessons]

    #         completed_lessons = 0
    #         progress_percentage = 0.0

    #         if user_id:
    #             try:
    #                 progress = self.get_module_progress(module_id, user_id)
    #                 completed_lessons = progress.completed_lessons_count
    #                 progress_percentage = progress.overall_progress_percentage
    #                 is_completed = progress.is_completed
    #             except Exception as e:
    #                 logger.warning(
    #                     "Could not get progress for module %s: %s", module_id, str(e)
    #                 )
    #                 completed_lessons = 0
    #                 progress_percentage = 0.0
    #                 is_completed = False

    #         has_module_test = False
    #         try:
    #             module_test = self._uow.module_tests.get_by_module_id(module_id)
    #             has_module_test = module_test is not None
    #         except Exception as e:
    #             logger.debug("Module %s has no test: %s", module_id, str(e))
    #             has_module_test = False

    #         is_completed = False
    #         if user_id and completed_lessons >= len(lessons_dto):
    #             is_completed = True

    #         return SubjectModuleWithLessonsDTO(
    #             **module_dto.dict(),
    #             lessons=lessons_dto,
    #             total_lessons=len(lessons_dto),
    #             completed_lessons=completed_lessons,
    #             progress_percentage=progress_percentage,
    #             has_module_test=has_module_test,
    #             is_completed=is_completed,
    #         )

    def count_lessons(self, module_id: int) -> int:
        """Count lessons in module"""
        with self._uow:
            return self._uow.subject_modules.count_lessons(module_id)

    @cached(strategy=CacheStrategy.USER, ttl=1800, resource="module_progress")
    def get_module_progress(self, module_id: int, user_id: UUID) -> UserModuleProgressDTO:
        """Get user progress for module"""
        with self._uow:
            self._uow.subject_modules.get_by_id(module_id)

            try:
                progress = self._uow.user_module_progress.get_by_module_and_user(module_id, user_id)
                if progress:
                    return UserModuleProgressDTO(
                        id=progress.id,
                        student_guid=progress.student_guid,
                        module_id=progress.module_id,
                        completed_lessons_count=progress.completed_lessons_count,
                        total_lessons_count=progress.total_lessons_count,
                        module_test_completed=progress.module_test_completed,
                        module_test_score=progress.module_test_score,
                        module_test_max_score=progress.module_test_max_score,
                        module_test_percentage=progress.module_test_percentage,
                        module_test_attempts_count=progress.module_test_attempts_count,
                        is_completed=progress.is_completed,
                        overall_progress_percentage=progress.overall_progress_percentage,
                        time_spent_seconds=progress.time_spent_seconds,
                        completed_at=progress.completed_at,
                        created_at=progress.created_at,
                        updated_at=progress.updated_at,
                    )
            except Exception as e:
                logger.debug(
                    "No progress found for module %s, user %s: %s",
                    module_id,
                    user_id,
                    str(e),
                )

            total_lessons = self.count_lessons(module_id)

            return UserModuleProgressDTO(
                student_guid=user_id,
                module_id=module_id,
                total_lessons_count=total_lessons,
                completed_lessons_count=0,
                module_test_completed=False,
                module_test_score=0,
                module_test_max_score=0,
                module_test_percentage=0.0,
                module_test_attempts_count=0,
                is_completed=False,
                overall_progress_percentage=0.0,
                time_spent_seconds=0,
                completed_at=None,
                created_at=None,
                updated_at=None,
            )

    def update_module_progress(
        self,
        module_id: int,
        user_id: UUID,
        lesson_completed: bool = False,
        test_completed: bool = False,
        time_spent: int = 0,
    ) -> UserModuleProgressDTO:
        """Update user progress for module"""
        with self._uow:
            progress = self.get_module_progress(module_id, user_id)

            if lesson_completed:
                progress.completed_lessons_count += 1

            if test_completed:
                progress.module_test_completed = True

            progress.time_spent_seconds += time_spent

            total_lessons = progress.total_lessons_count
            if total_lessons > 0:
                lesson_progress = progress.completed_lessons_count / total_lessons
                test_progress = 1.0 if progress.module_test_completed else 0.0
                progress.overall_progress_percentage = (lesson_progress + test_progress) / 2 * 100

            if progress.completed_lessons_count >= total_lessons and progress.module_test_completed:
                progress.is_completed = True

            self._uow.user_module_progress.update_or_create(progress)
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id, user_id=user_id)

            return progress

    # def get_subject_modules_with_progress(
    #     self, subject_id: int, user_id: UUID
    # ) -> builtins.list[SubjectModuleWithLessonsDTO]:
    #     """Получить модули предмета с прогрессом пользователя"""
    #     modules, _ = self.get_by_subject(subject_id)
    #     result = []

    #     for module in modules:
    #         module_with_progress = self.get_with_lessons(module.id, user_id)
    #         result.append(module_with_progress)

    #     return result

    # def calculate_subject_progress(
    #     self, subject_id: int, user_id: UUID
    # ) -> dict[str, Any]:
    #     """Рассчитать общий прогресс по предмету"""
    #     modules_with_progress = self.get_subject_modules_with_progress(
    #         subject_id, user_id
    #     )

    #     if not modules_with_progress:
    #         return {
    #             "subject_id": subject_id,
    #             "total_modules": 0,
    #             "completed_modules": 0,
    #             "total_lessons": 0,
    #             "completed_lessons": 0,
    #             "overall_progress": 0.0,
    #             "total_time_spent_minutes": 0,
    #         }

    #     total_modules = len(modules_with_progress)
    #     completed_modules = sum(1 for m in modules_with_progress if m.is_completed)

    #     total_lessons = sum(m.total_lessons for m in modules_with_progress)
    #     completed_lessons = sum(m.completed_lessons for m in modules_with_progress)

    #     total_time_spent = 0
    #     for module in modules_with_progress:
    #         progress = self.get_module_progress(module.id, user_id)
    #         total_time_spent += progress.time_spent_seconds // 60

    #     overall_progress = (
    #         (completed_modules / total_modules * 100) if total_modules > 0 else 0
    #     )

    #     return {
    #         "subject_id": subject_id,
    #         "total_modules": total_modules,
    #         "completed_modules": completed_modules,
    #         "total_lessons": total_lessons,
    #         "completed_lessons": completed_lessons,
    #         "overall_progress": overall_progress,
    #         "total_time_spent_minutes": total_time_spent,
    #         "modules": modules_with_progress,
    #     }

    # def get_subject_modules_with_lessons(
    #     self, subject_id: int, user_id: UUID
    # ) -> SubjectModulesResponseDTO:
    #     """Получить модули предмета с уроками"""
    #     with self._uow:
    #         subject = self._uow.subjects.get_by_id(subject_id)

    #         modules, total_modules = self.get_by_subject(subject_id)

    #         modules_with_lessons = []
    #         completed_modules = 0

    #         for module in modules:
    #             lessons_with_details = (
    #                 self._lesson_service.get_module_lessons_with_trainers(
    #                     module.id, user_id
    #                 )
    #             )

    #             short_lessons = []
    #             completed_lessons = 0

    #             for lesson in lessons_with_details:
    #                 test_results = None
    #                 if lesson.is_completed:
    #                     test_results = (
    #                         lesson.progress.test_score / lesson.progress.test_max_score
    #                         if lesson.progress.test_max_score > 0
    #                         else 0
    #                     )

    #                 start_score = 0  # TODO: in the future based on lesson settings
    #                 with_materials = True  # TODO: in the future based on lesson content
    #                 short_lessons.append(
    #                     ModuleLessonShortDTO(
    #                         id=lesson.id,
    #                         name=lesson.title,
    #                         topic_id=lesson.topic_id,
    #                         trainer_id=lesson.trainer_id,
    #                         is_completed=lesson.is_completed,
    #                         test_result=test_results,
    #                         start_score=start_score,
    #                         with_materials=with_materials,
    #                     )
    #                 )

    #                 if lesson.is_completed:
    #                     completed_lessons += 1

    #             total_lessons = len(short_lessons)
    #             progress_percentage = 0.0
    #             is_module_completed = False

    #             if total_lessons > 0:
    #                 progress_percentage = (completed_lessons / total_lessons) * 100
    #                 is_module_completed = completed_lessons == total_lessons

    #             if is_module_completed:
    #                 completed_modules += 1

    #             modules_with_lessons.append(
    #                 ModuleInSubjectResponseDTO(
    #                     id=module.id,
    #                     title=module.title,
    #                     description=module.description,
    #                     total_lessons=total_lessons,
    #                     lessons=short_lessons,
    #                     completed_lessons=completed_lessons,
    #                     progress_percentage=progress_percentage,
    #                     is_completed=is_module_completed,
    #                 )
    #             )

    #         overall_progress = 0.0
    #         if total_modules > 0:
    #             overall_progress = (completed_modules / total_modules) * 100

    #         return SubjectModulesResponseDTO(
    #             id=subject.id,
    #             name=subject.name,
    #             modules=modules_with_lessons,
    #             total_modules=total_modules,
    #             completed_modules=completed_modules,
    #             overall_progress=overall_progress,
    #         )

    def get_subject_modules_response(self, subject_id: int, user_id: UUID) -> SubjectModulesResponseDTO:
        """Получить модули предмета в нужном формате"""
        with self._uow:
            try:
                subject = self._uow.subjects.get_by_id(subject_id)
            except Exception:
                raise SubjectNotFoundService(f"Subject with id {subject_id} not found")

            modules, total_modules = self.get_by_subject(subject_id)

            modules_with_lessons = []
            completed_modules = 0

            lesson_service = ModuleLessonService(self._uow, self._cache_service)

            for module in modules:
                short_lessons = lesson_service.get_module_lessons_short(module.id, user_id)

                completed_lessons = sum(1 for lesson in short_lessons if lesson.is_completed)
                total_lessons = len(short_lessons)

                progress_percentage = 0.0
                is_module_completed = False

                if total_lessons > 0:
                    progress_percentage = (completed_lessons / total_lessons) * 100
                    is_module_completed = completed_lessons == total_lessons

                if is_module_completed:
                    completed_modules += 1

                modules_with_lessons.append(
                    ModuleInSubjectResponseDTO(
                        **module.dict(),
                        total_lessons=total_lessons,
                        lessons=short_lessons,
                        completed_lessons=completed_lessons,
                        progress_percentage=progress_percentage,
                        is_completed=is_module_completed,
                    )
                )

            overall_progress = 0.0
            if total_modules > 0:
                overall_progress = (completed_modules / total_modules) * 100

            return SubjectModulesResponseDTO(
                id=subject.id,
                name=subject.name,
                modules=modules_with_lessons,
                total_modules=total_modules,
                completed_modules=completed_modules,
                overall_progress=overall_progress,
            )

    def update_module_order(self, subject_id: int, module_orders: builtins.list[dict[str, int]]) -> None:
        """Обновить порядок модулей в предмете"""
        with self._uow:
            try:
                self._uow.subjects.get_by_id(subject_id)

                self._uow.subject_modules.update_order(subject_id, module_orders)
                self._uow.commit()

                self._invalidate_module_cache(subject_id=subject_id)
                logger.info("Updated order for modules in subject %s", subject_id)

            except Exception as e:
                self._uow.rollback()
                raise ModuleOrderUpdateError(str(e))

    def get_module_with_test_info(self, module_id: int) -> ModuleWithTestInfoDTO:
        """Получить модуль с информацией о тесте"""
        with self._uow:
            module = self._uow.subject_modules.get_with_test_info(module_id)

            module_dto = to_subject_module_service(module)

            has_module_test = False
            module_test_id = None
            module_test_title = None
            module_test_questions_count = 0

            try:
                module_test = self._uow.module_tests.get_by_module_id(module_id)
                if module_test:
                    has_module_test = True
                    module_test_id = module_test.id
                    module_test_title = module_test.title
                    module_test_questions_count = self._get_module_test_questions_count(module_test_id)
            except Exception as e:
                logger.debug("Module %s has no test: %s", module_id, str(e))

            return ModuleWithTestInfoDTO(
                **module_dto.dict(),
                has_module_test=has_module_test,
                module_test_id=module_test_id,
                module_test_title=module_test_title,
                module_test_questions_count=module_test_questions_count,
            )

    def _get_module_test_questions_count(self, module_test_id: int) -> int:
        """Получить количество вопросов в тесте модуля"""
        with self._uow:
            return self._uow.module_tests.get_questions_count(module_test_id)

    def create_module_test(self, module_id: int, create_dto: ModuleTestCreateServiceDTO) -> ModuleTestServiceDTO:
        """Создать тест модуля"""
        with self._uow:
            self._uow.subject_modules.get_by_id(module_id)

            existing_test = self._uow.module_tests.get_by_module_id(module_id)
            if existing_test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} already exists")

            test_dto = ModuleTestCreateRepositoryDTO(module_id=module_id, **create_dto.dict(exclude={"module_id"}))
            created_test = self._uow.module_tests.create(test_dto)
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id)
            logger.info("Created module test for module %s", module_id)

            return ModuleTestServiceDTO.model_validate(created_test)

    def get_module_test(self, module_id: int) -> ModuleTestServiceDTO:
        """Получить тест модуля"""
        with self._uow:
            test = self._uow.module_tests.get_by_module_id(module_id)
            if not test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} not found")
            return ModuleTestServiceDTO.model_validate(test)

    def update_module_test(self, module_id: int, update_dto: ModuleTestUpdateServiceDTO) -> ModuleTestServiceDTO:
        """Обновить тест модуля"""
        with self._uow:
            test = self._uow.module_tests.get_by_module_id(module_id)
            if not test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} not found")

            updated_test = self._uow.module_tests.update(
                test.id,
                ModuleTestUpdateRepositoryDTO(**update_dto.dict(exclude_unset=True)),
            )
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id)
            logger.info("Updated module test for module %s", module_id)

            return ModuleTestServiceDTO.model_validate(updated_test)

    def delete_module_test(self, module_id: int) -> None:
        """Удалить тест модуля"""
        with self._uow:
            test = self._uow.module_tests.get_by_module_id(module_id)
            if not test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} not found")

            self._uow.module_tests.delete(test.id)
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id)
            logger.info("Deleted module test for module %s", module_id)

    def add_questions_to_module_test(self, module_id: int, question_ids: builtins.list[int]) -> None:
        """Добавить вопросы в тест модуля"""
        with self._uow:
            test = self._uow.module_tests.get_by_module_id(module_id)
            if not test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} not found")

            self._uow.module_tests.add_questions(test.id, question_ids)
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id)
            logger.info("Added %s questions to module test %s", len(question_ids), test.id)

    def remove_question_from_module_test(self, module_id: int, question_id: int) -> None:
        """Удалить вопрос из теста модуля"""
        with self._uow:
            test = self._uow.module_tests.get_by_module_id(module_id)
            if not test:
                raise ModuleTestNotFoundService(f"Module test for module {module_id} not found")

            self._uow.module_tests.remove_question(test.id, question_id)
            self._uow.commit()

            self._invalidate_module_cache(module_id=module_id)
            logger.info("Removed question %s from module test %s", question_id, test.id)

    def get_lessons_count_by_modules(self, module_ids: builtins.list[int]) -> dict[int, int]:
        """Get lesson count for each module"""
        with self._uow:
            return self._uow.subject_modules.get_lessons_count_by_modules(module_ids)


# ========== Module Lesson Service ==========


class ModuleLessonServiceInterface(
    BaseServiceInterface[
        ModuleLessonCreateServiceDTO,
        ModuleLessonUpdateServiceDTO,
        ModuleLessonServiceDTO,
    ]
):
    """Interface for module lesson management operations"""

    def get_by_module(
        self,
        module_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[ModuleLessonServiceDTO], int]:
        """Get lessons by module ID"""
        raise NotImplementedError

    def get_with_details(self, lesson_id: int, user_id: UUID | None = None) -> ModuleLessonWithDetailsDTO:
        """Get lesson with detailed information"""
        raise NotImplementedError

    def get_lesson_progress(self, lesson_id: int, user_id: UUID) -> UserLessonProgressDTO:
        """Get user progress for lesson"""
        raise NotImplementedError

    def update_lesson_progress(
        self,
        lesson_id: int,
        user_id: UUID,
        # watched_video: bool = False,
        # viewed_presentation: bool = False,
        # read_content: bool = False,
        completed_test: bool = False,
        test_score: int = 0,
        test_max_score: int = 0,
        time_spent: int = 0,
    ) -> UserLessonProgressDTO:
        """Update user progress for lesson"""
        raise NotImplementedError


class ModuleLessonService(ModuleLessonServiceInterface):
    """Implementation of module lesson management service"""

    def __init__(self, uow: UnitOfWorkTests, cache_service: CacheService):
        self._uow = uow
        self._cache_service = cache_service

    def _invalidate_lesson_cache(
        self,
        lesson_id: int | None = None,
        module_id: int | None = None,
        user_id: UUID | None = None,
    ):
        """Invalidate lesson cache"""
        resources = [
            "module_lessons",
            "module_lesson",
            "lessons_by_module",
            "lesson_with_details",
            "lesson_progress",
        ]

        deleted = self._cache_service.invalidate_by_resources(resources)

        if lesson_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="module_lesson",
                    params=f"id:{lesson_id}",
                )
            )

        if module_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.GLOBAL,
                    resource="lessons_by_module",
                    params=f"module_id:{module_id}",
                )
            )

        if user_id and lesson_id:
            self._cache_service.delete(
                self._cache_service.make_key(
                    CacheStrategy.USER,
                    resource="lesson_progress",
                    user_id=str(user_id),
                    params=f"lesson_id:{lesson_id}",
                )
            )

        logger.info("Invalidated lesson cache, deleted %s keys", deleted)

    def create(self, create_dto: ModuleLessonCreateServiceDTO) -> ModuleLessonServiceDTO:
        """Create a new module lesson"""
        with self._uow:
            try:
                self._uow.subject_modules.get_by_id(create_dto.module_id)

                if create_dto.topic_id:
                    self._uow.topics.get_by_id(create_dto.topic_id)

                created_lesson = self._uow.module_lessons.create(to_module_lesson_repository(create_dto))
                self._uow.commit()
                self._invalidate_lesson_cache(module_id=create_dto.module_id)
                logger.info("Created lesson: %s", created_lesson.id)
                return to_module_lesson_service(created_lesson)

            except SubjectModuleNotFoundService:
                raise SubjectModuleNotFoundService(f"Module with id {create_dto.module_id} not found")
            except TopicNotFoundService:
                raise TopicNotFoundService(f"Topic with id {create_dto.topic_id} not found")
            except LessonSameNameService as e:
                raise LessonSameNameService(
                    f"Lesson '{create_dto.title}' already exists in module",
                    existing_lesson_id=e.existing_lesson_id,
                )
            except LessonIntegrityErrorService as e:
                raise LessonIntegrityErrorService(str(e))

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="module_lesson")
    def get_by_id(self, lesson_id: int) -> ModuleLessonServiceDTO:
        """Get lesson by ID"""
        with self._uow:
            try:
                lesson = self._uow.module_lessons.get_by_id(lesson_id)
                return to_module_lesson_service(lesson)
            except ModuleLessonNotFoundService:
                raise ModuleLessonNotFoundService(f"Lesson with id {lesson_id} not found")

    def update(self, lesson_id: int, update_dto: ModuleLessonUpdateServiceDTO) -> ModuleLessonServiceDTO:
        """Update lesson by ID"""
        with self._uow:
            try:
                lesson = self._uow.module_lessons.get_by_id(lesson_id)
                updated_lesson = self._uow.module_lessons.update(lesson_id, to_module_lesson_repository(update_dto))
                self._uow.commit()
                self._invalidate_lesson_cache(lesson_id, lesson.module_id)
                logger.info("Updated lesson: %s", lesson_id)
                return to_module_lesson_service(updated_lesson)

            except ModuleLessonNotFoundService:
                raise ModuleLessonNotFoundService(f"Lesson with id {lesson_id} not found")
            except LessonSameNameService as e:
                raise LessonSameNameService("Lesson name conflict", existing_lesson_id=e.existing_lesson_id)
            except LessonIntegrityErrorService as e:
                raise LessonIntegrityErrorService(str(e))

    def delete(self, lesson_id: int) -> None:
        """Delete lesson by ID"""
        with self._uow:
            try:
                lesson = self._uow.module_lessons.get_by_id(lesson_id)
                self._uow.module_lessons.delete(lesson_id)
                self._uow.commit()
                self._invalidate_lesson_cache(lesson_id, lesson.module_id)
                logger.info("Deleted lesson: %s", lesson_id)

            except ModuleLessonNotFoundService:
                raise ModuleLessonNotFoundService(f"Lesson with id {lesson_id} not found")
            except LessonIdViolatesNotNullService:
                raise LessonIdViolatesNotNullService(f"Cannot delete lesson {lesson_id} due to foreign key constraints")

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="module_lessons")
    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[list[ModuleLessonServiceDTO], int]:
        """Get paginated list of lessons"""
        with self._uow:
            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            lessons, total_count = self._uow.module_lessons.list(
                offset, page_size, search, sort_columns, is_sort_ascendings
            )

            return [to_module_lesson_service(lesson) for lesson in lessons], total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=3600, resource="lessons_by_module")
    def get_by_module(
        self,
        module_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "asc",
    ) -> tuple[builtins.list[ModuleLessonServiceDTO], int]:
        """Get lessons by module ID"""
        with self._uow:
            self._uow.subject_modules.get_by_id(module_id)

            sort_columns = [sort_by] if sort_by else None
            is_sort_ascendings = [sort_order == "asc"] if sort_by else None

            offset = (page - 1) * page_size
            lessons, total_count = self._uow.module_lessons.get_by_module(
                module_id, offset, page_size, search, sort_columns, is_sort_ascendings
            )

            return [to_module_lesson_service(lesson) for lesson in lessons], total_count

    @cached(strategy=CacheStrategy.GLOBAL, ttl=1800, resource="lesson_with_details")
    def get_with_details(self, lesson_id: int, user_id: UUID | None = None) -> ModuleLessonWithDetailsDTO:
        """Get lesson with detailed information"""
        with self._uow:
            lesson = self._uow.module_lessons.get_by_id(lesson_id)
            lesson_dto = to_module_lesson_service(lesson)

            module = self._uow.subject_modules.get_by_id(lesson.module_id)
            subject = self._uow.subjects.get_by_id(module.subject_id)

            topic_name = None
            if lesson.topic_id:
                try:
                    topic = self._uow.topics.get_by_id(lesson.topic_id)
                    topic_name = topic.name
                except TopicNotFoundService:
                    pass

            has_test = False
            is_linked_to_topic = lesson.topic_id is not None
            trainer_id = None
            lesson_test_id = None
            trainer_last_attempt_id = None

            if is_linked_to_topic:
                trainers = self._uow.trainers.get_trainers_by_topic_id(lesson.topic_id)
                if trainers:
                    has_test = True
                    trainer_id = trainers[0].id
                    if user_id:
                        try:
                            attempts = self._uow.trainer_attempts.get_user_trainer_attempts(str(user_id), trainer_id)
                            completed_attempts = [attempt for attempt in attempts if attempt.status == Status.completed]
                            if completed_attempts:
                                trainer_last_attempt_id = completed_attempts[0].id
                        except Exception as e:
                            logger.warning(
                                "Could not get trainer attempts for user %s, trainer %s: %s",
                                user_id,
                                trainer_id,
                                str(e),
                            )
            else:
                try:
                    lesson_test = self._uow.lesson_tests.get_by_lesson_id(lesson_id)
                    has_test = True
                    lesson_test_id = lesson_test.id
                except Exception as e:
                    logger.debug("Lesson %s has no test: %s", lesson_id, str(e))
                    has_test = False

            if user_id:
                try:
                    self.get_lesson_progress(lesson_id, user_id)
                except Exception as e:
                    logger.warning("Could not get progress for lesson %s: %s", lesson_id, str(e))

            return ModuleLessonWithDetailsDTO(
                **lesson_dto.dict(),
                module_title=module.title,
                subject_name=subject.name,
                topic_name=topic_name,
                has_test=has_test,
                is_linked_to_topic=is_linked_to_topic,
                trainer_id=trainer_id,
                lesson_test_id=lesson_test_id,
                trainer_last_attempt_id=trainer_last_attempt_id,
            )

    # @cached(strategy=CacheStrategy.USER, ttl=1800, resource="lesson_progress")
    def get_lesson_progress(self, lesson_id: int, user_id: UUID) -> UserLessonProgressDTO:
        """Get user progress for lesson"""
        with self._uow:
            self._uow.module_lessons.get_by_id(lesson_id)

            try:
                progress = self._uow.user_lesson_progress.get_by_lesson_and_user(lesson_id, user_id)
                if progress:
                    return UserLessonProgressDTO(
                        id=progress.id,
                        student_guid=progress.student_guid,
                        lesson_id=progress.lesson_id,
                        # watched_video=progress.watched_video,
                        # viewed_presentation=progress.viewed_presentation,
                        # read_content=progress.read_content,
                        completed_test=progress.completed_test,
                        test_score=progress.test_score,
                        test_max_score=progress.test_max_score,
                        test_percentage=progress.test_percentage,
                        test_attempts_count=progress.test_attempts_count,
                        time_spent_seconds=progress.time_spent_seconds,
                        is_completed=progress.is_completed,
                        completed_at=progress.completed_at,
                        last_accessed_at=progress.last_accessed_at,
                        created_at=progress.created_at,
                        updated_at=progress.updated_at,
                    )
            except Exception:
                logger.info("No progress found for lesson %s, user %s", lesson_id, user_id)

            return UserLessonProgressDTO(
                student_guid=user_id,
                lesson_id=lesson_id,
                # watched_video=False,
                # viewed_presentation=False,
                # read_content=False,
                completed_test=False,
                test_score=0,
                test_max_score=0,
                test_percentage=0.0,
                test_attempts_count=0,
                time_spent_seconds=0,
                is_completed=False,
                completed_at=None,
                last_accessed_at=None,
                created_at=None,
                updated_at=None,
            )

    def update_lesson_progress(
        self,
        lesson_id: int,
        user_id: UUID,
        # watched_video: bool = False,
        # viewed_presentation: bool = False,
        # read_content: bool = False,
        completed_test: bool = False,
        test_score: int = 0,
        test_max_score: int = 0,
        time_spent: int = 0,
    ) -> UserLessonProgressDTO:
        logger.info("Updating progress for lesson %s, user %s", lesson_id, user_id)
        logger.debug(
            "Params: completed_test=%s, test_score=%s/%s",
            completed_test,
            test_score,
            test_max_score,
        )

        with self._uow:
            progress = self.get_lesson_progress(lesson_id, user_id)
            logger.debug("Existing progress: %s", progress)

            # if watched_video:
            #     progress.watched_video = True
            # if viewed_presentation:
            #     progress.viewed_presentation = True
            # if read_content:
            #     progress.read_content = True

            if completed_test:
                progress.completed_test = True
                progress.test_score = test_score
                progress.test_max_score = test_max_score
                if test_max_score > 0:
                    progress.test_percentage = (test_score / test_max_score) * 100
                progress.test_attempts_count += 1

            progress.time_spent_seconds += time_spent
            progress.last_accessed_at = datetime.now()
            progress.is_completed = progress.completed_test

            if progress.is_completed and not progress.completed_at:
                progress.completed_at = datetime.now()

            if progress.id is None:
                progress_data = progress.dict(exclude={"id", "created_at", "updated_at"})
                progress_data["created_at"] = datetime.now()
                progress_data["updated_at"] = datetime.now()
                new_progress = self._uow.user_lesson_progress.create(progress_data)
                progress.id = new_progress.id
                progress.created_at = new_progress.created_at
                progress.updated_at = new_progress.updated_at
                logger.info("Created new progress record with id %s", progress.id)
            else:
                progress.updated_at = datetime.now()
                self._uow.user_lesson_progress.update_or_create(progress)
                logger.info("Updated existing progress record %s", progress.id)

            self._uow.commit()
            logger.info(
                "Progress after commit: is_completed=%s, completed_test=%s",
                progress.is_completed,
                progress.completed_test,
            )

            if progress.is_completed:
                lesson = self._uow.module_lessons.get_by_id(lesson_id)
                module_service = SubjectModuleService(self._uow, self._cache_service)
                module_service.update_module_progress(
                    lesson.module_id,
                    user_id,
                    lesson_completed=True,
                    time_spent=time_spent,
                )

                cashback_service = CashbackService(self._uow, self._cache_service)
                cashback_service.check_and_update(user_id)

            self._invalidate_lesson_cache(lesson_id=lesson_id, user_id=user_id)

            return progress

    # def get_lessons_by_module_with_progress(
    #     self, module_id: int, user_id: UUID
    # ) -> builtins.list[ModuleLessonServiceDTO]:
    #     """Получить уроки модуля с прогрессом пользователя"""
    #     lessons, _ = self.get_by_module(module_id)
    #     result = []

    #     for lesson in lessons:
    #         lesson_dto = to_module_lesson_service(lesson)
    #         progress = self.get_lesson_progress(lesson.id, user_id)
    #         result.append(
    #             {
    #                 **lesson_dto.dict(),
    #                 "progress": progress,
    #                 "is_started": progress.time_spent_seconds > 0,
    #                 "is_completed": progress.is_completed,
    #             }
    #         )

    #     return result

    def _get_trainer_id_for_lesson(self, lesson) -> int | None:
        """Получить ID тренажёра для урока"""
        if not lesson.topic_id:
            return None

        try:
            trainers = self._uow.trainers.get_trainers_by_topic_id(lesson.topic_id)
            if trainers:
                return trainers[0].id
        except Exception as e:
            logger.warning("Could not get trainer for topic %s: %s", lesson.topic_id, str(e))

        return None

    def get_module_lessons_with_trainers(
        self, module_id: int, user_id: UUID
    ) -> builtins.list[ModuleLessonWithTrainerDTO]:
        """Получить уроки модуля с информацией о тренажёрах"""
        with self._uow:
            lessons, _ = self.get_by_module(module_id)
            result = []

            for lesson in lessons:
                progress = self.get_lesson_progress(lesson.id, user_id)
                trainer_id = self._get_trainer_id_for_lesson(lesson)

                topic_name = None
                if lesson.topic_id:
                    try:
                        topic = self._uow.topics.get_by_id(lesson.topic_id)
                        topic_name = topic.name
                    except Exception as e:
                        logger.warning("Could not get topic %s: %s", lesson.topic_id, str(e))

                result.append(
                    ModuleLessonWithTrainerDTO(
                        **lesson.dict(),
                        progress=progress,
                        is_started=progress.time_spent_seconds > 0,
                        is_completed=progress.is_completed,
                        trainer_id=trainer_id,
                        topic_name=topic_name,
                    )
                )

            return result

    # def get_module_lessons_response(
    #     self, module_id: int, user_id: UUID
    # ) -> builtins.list[ModuleLessonResponseDTO]:
    #     """Получить уроки модуля в нужном формате"""
    #     lessons, _ = self.get_by_module(module_id)
    #     result = []

    #     for lesson in lessons:
    #         progress = self.get_lesson_progress(lesson.id, user_id)

    #         trainer_id = None
    #         if lesson.topic_id:
    #             try:
    #                 trainers = self._uow.trainers.get_trainers_by_topic_id(
    #                     lesson.topic_id
    #                 )
    #                 if trainers:
    #                     trainer_id = trainers[0].id
    #             except Exception as e:
    #                 logger.warning(
    #                     "Could not get trainer for topic %s: %s",
    #                     lesson.topic_id,
    #                     str(e),
    #                 )

    #         short_progress = LessonProgressShortDTO(
    #             completed_test=progress.completed_test,
    #             test_score=progress.test_score,
    #             test_max_score=progress.test_max_score,
    #             test_percentage=progress.test_percentage,
    #             test_attempts_count=progress.test_attempts_count,
    #             time_spent_seconds=progress.time_spent_seconds,
    #         )

    #         result.append(
    #             ModuleLessonResponseDTO(
    #                 title=lesson.title,
    #                 description=lesson.description,
    #                 video_url=lesson.video_url,
    #                 presentation_url=lesson.presentation_url,
    #                 topic_id=lesson.topic_id,
    #                 trainer_id=trainer_id,
    #                 progress=short_progress,
    #                 is_completed=progress.is_completed,
    #             )
    #         )

    #     return result

    def get_module_lessons_short(self, module_id: int, user_id: UUID) -> builtins.list[ModuleLessonShortDTO]:
        """Получить краткую информацию об уроках модуля"""
        lessons, _ = self.get_by_module(module_id)
        # logger.info(f"Fetched {len(lessons)} lessons for module {module_id}")
        result = []

        for lesson in lessons:
            progress = self.get_lesson_progress(lesson.id, user_id)
            logger.debug(
                "Lesson %s progress: is_completed=%s, completed_test=%s",
                lesson.id,
                progress.is_completed,
                progress.completed_test,
            )

            trainer_id = None
            if lesson.topic_id:
                try:
                    trainers = self._uow.trainers.get_trainers_by_topic_id(lesson.topic_id)
                    if trainers:
                        trainer_id = trainers[0].id
                    # logger.info(
                    #     f"Lesson {lesson.id} is linked to topic {lesson.topic_id}, found trainer {trainer_id}"
                    # )
                except Exception as e:
                    logger.warning(
                        "Could not get trainer for topic %s: %s",
                        lesson.topic_id,
                        str(e),
                    )
                    continue

            test_results = None
            if progress.completed_test and progress.test_max_score > 0:
                test_results = progress.test_score / progress.test_max_score
                # logger.info(
                #     f"Calculated test results for lesson {lesson.id}: {test_results:.2f}"
                # )
            elif trainer_id:
                # logger.info(
                #     f"Lesson {lesson.id} is linked to trainer {trainer_id}, calculating test results based on trainer attempts"
                # )
                try:
                    with self._uow:
                        attempts = self._uow.trainer_attempts.get_user_trainer_attempts(str(user_id), trainer_id)
                        completed_attempts = [attempt for attempt in attempts if attempt.status == Status.completed]
                        if completed_attempts:
                            # logger.info(
                            #     f"Found {len(completed_attempts)} completed attempts for user {user_id} on trainer {trainer_id}, calculating test results based on the latest attempt"
                            # )
                            # Берем последнюю завершенную попытку
                            last_attempt = completed_attempts[0]
                            attempt_stats = self._uow.trainer_attempts.get_attempt_statistic(last_attempt.id)
                            if attempt_stats:
                                total = attempt_stats.get("total_questions", 0)
                                correct = attempt_stats.get("correct", 0)
                                if total > 0:
                                    test_results = correct / total
                                # logger.info(
                                #     f"Calculated test results for lesson {lesson.id} based on trainer attempts: {test_results:.2f}"
                                # )
                except Exception as e:
                    logger.warning("Could not get trainer attempts: %s", str(e))

            start_score = 0  # TODO: get from progress or test results
            with_materials = bool(
                lesson.description or lesson.video_url or lesson.presentation_url
            )  # TODO: can be optimized by checking in DB if materials exist instead of fetching all data here, and could be managed from admin panel when creating/updating lesson

            result.append(
                ModuleLessonShortDTO(
                    id=lesson.id,
                    name=lesson.title,
                    topic_id=lesson.topic_id,
                    trainer_id=trainer_id,
                    is_completed=progress.is_completed,
                    test_result=test_results,
                    start_score=start_score,
                    with_materials=with_materials,
                )
            )

        return result

    def update_lesson_order(self, module_id: int, lesson_orders: builtins.list[dict[str, int]]) -> None:
        """Обновить порядок уроков в модуле"""
        with self._uow:
            try:
                self._uow.subject_modules.get_by_id(module_id)

                self._uow.module_lessons.update_order(module_id, lesson_orders)
                self._uow.commit()

                self._invalidate_lesson_cache(module_id=module_id)
                logger.info("Updated order for lessons in module %s", module_id)

            except Exception as e:
                self._uow.rollback()
                raise LessonOrderUpdateError(str(e))

    def update_lesson_media(
        self,
        lesson_id: int,
        video_url: str | None = None,
        presentation_url: str | None = None,
    ) -> ModuleLessonServiceDTO:
        """Обновить медиа-файлы урока"""
        with self._uow:
            try:
                updated_lesson = self._uow.module_lessons.update_media(lesson_id, video_url, presentation_url)
                self._uow.commit()

                self._invalidate_lesson_cache(lesson_id=lesson_id)
                logger.info("Updated media for lesson %s", lesson_id)

                return to_module_lesson_service(updated_lesson)

            except ModuleLessonNotFoundService:
                raise ModuleLessonNotFoundService(f"Lesson with id {lesson_id} not found")
            except Exception as e:
                self._uow.rollback()
                raise LessonIntegrityErrorService(str(e))

    def publish_lesson(
        self,
        lesson_id: int,
        is_published: bool,
        published_at: datetime | None = None,
    ) -> ModuleLessonServiceDTO:
        """Опубликовать или снять урок"""
        with self._uow:
            try:
                if is_published:
                    lesson = self._uow.module_lessons.get_by_id(lesson_id)
                    if not lesson.topic_id:
                        try:
                            self._uow.lesson_tests.get_by_lesson_id(lesson_id)
                        except Exception:
                            raise LessonNotPublishedError(
                                "Урок должен быть привязан к теме или иметь собственный тест для публикации"
                            )

                updated_lesson = self._uow.module_lessons.publish_lesson(lesson_id, is_published, published_at)
                self._uow.commit()

                self._invalidate_lesson_cache(lesson_id=lesson_id)
                action = "published" if is_published else "unpublished"
                logger.info("%s lesson %s", action.capitalize(), lesson_id)

                return to_module_lesson_service(updated_lesson)

            except ModuleLessonNotFoundService:
                raise ModuleLessonNotFoundService(f"Lesson with id {lesson_id} not found")
            except Exception as e:
                self._uow.rollback()
                raise LessonIntegrityErrorService(str(e))

    def get_lesson_with_test_info(self, lesson_id: int) -> LessonWithTestInfoDTO:
        """Получить урок с информацией о тесте"""
        with self._uow:
            lesson = self._uow.module_lessons.get_with_test_info(lesson_id)
            lesson_dto = to_module_lesson_service(lesson)

            has_test = False
            test_id = None
            test_title = None
            questions_count = 0

            if lesson.topic_id:
                trainers = self._uow.trainers.get_trainers_by_topic_id(lesson.topic_id)
                if trainers:
                    has_test = True
                    test_id = trainers[0].id
                    test_title = trainers[0].name
                    questions_count = self._get_trainer_questions_count(test_id)
            else:
                try:
                    lesson_test = self._uow.lesson_tests.get_by_lesson_id(lesson_id)
                    has_test = True
                    test_id = lesson_test.id
                    test_title = lesson_test.title
                    questions_count = self._get_lesson_test_questions_count(test_id)
                except Exception as e:
                    logger.debug("Something happened: %s", e)
                    pass

            return LessonWithTestInfoDTO(
                **lesson_dto.dict(),
                has_test=has_test,
                test_id=test_id,
                test_title=test_title,
                questions_count=questions_count,
            )

    def _get_trainer_questions_count(self, trainer_id: int) -> int:
        """Получить количество вопросов в тренажёре"""
        with self._uow:
            return self._uow.trainers.count_questions_by_trainer(trainer_id)

    def _get_lesson_test_questions_count(self, test_id: int) -> int:
        """Получить количество вопросов в тесте урока"""
        with self._uow:
            return self._uow.lesson_tests.get_questions_count(test_id)
