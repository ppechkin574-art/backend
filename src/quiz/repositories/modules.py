import builtins
import logging
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quiz.dtos.modules import (
    LessonTestCreateRepositoryDTO,
    LessonTestRepositoryDTO,
    LessonTestUpdateRepositoryDTO,
    ModuleLessonCreateRepositoryDTO,
    ModuleLessonRepositoryDTO,
    ModuleLessonUpdateRepositoryDTO,
    ModuleTestCreateRepositoryDTO,
    ModuleTestRepositoryDTO,
    ModuleTestUpdateRepositoryDTO,
    SubjectModuleCreateRepositoryDTO,
    SubjectModuleRepositoryDTO,
    SubjectModuleUpdateRepositoryDTO,
)
from quiz.exceptions import (
    LessonIdViolatesNotNullRepository,
    LessonIntegrityErrorRepository,
    LessonOrderUpdateError,
    LessonSameNameRepository,
    LessonTestNotFoundRepository,
    ModuleIdViolatesNotNullRepository,
    ModuleIntegrityErrorRepository,
    ModuleLessonNotFoundRepository,
    ModuleOrderUpdateError,
    ModuleSameNameRepository,
    ModuleTestNotFoundRepository,
    QuestionNotFoundError,
    SubjectModuleNotFoundRepository,
    SubjectNotFoundRepository,
    TestQuestionAlreadyExistsError,
    TopicNotFoundRepository,
)
from quiz.models.edu_content import Question, Subject, Topic
from quiz.models.modular_edu import (
    LessonTest,
    LessonTestQuestion,
    ModuleLesson,
    ModuleTest,
    ModuleTestQuestion,
    SubjectModule,
)
from quiz.services.base import BaseRepositoryInterface

logger = logging.getLogger(__name__)


class SubjectModuleRepositoryInterface(
    BaseRepositoryInterface[
        SubjectModuleCreateRepositoryDTO,
        SubjectModuleUpdateRepositoryDTO,
        SubjectModuleRepositoryDTO,
    ]
):
    """Interface for subject module data access operations"""

    def get_by_subject(
        self,
        subject_id: int,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[SubjectModuleRepositoryDTO], int]:
        """Get modules by subject ID"""
        raise NotImplementedError

    def count_lessons(self, module_id: int) -> int:
        """Count lessons in module"""
        raise NotImplementedError


class SubjectModuleRepository(SubjectModuleRepositoryInterface):
    """Implementation of subject module data access operations"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: SubjectModuleCreateRepositoryDTO) -> SubjectModuleRepositoryDTO:
        """Create a new subject module"""
        subject = self._session.get(Subject, create_dto.subject_id)
        if not subject:
            raise SubjectNotFoundRepository(f"Subject with id {create_dto.subject_id} not found")

        instance = SubjectModule(**create_dto.model_dump())
        self._session.add(instance)

        try:
            self._session.flush()
            return SubjectModuleRepositoryDTO.model_validate(instance)
        except IntegrityError as e:
            if "subject_modules_title_subject_id_key" in str(e):
                existing = self._session.execute(
                    select(SubjectModule).where(
                        SubjectModule.subject_id == create_dto.subject_id,
                        SubjectModule.title == create_dto.title,
                    )
                ).scalar_one_or_none()
                if existing:
                    raise ModuleSameNameRepository(
                        f"Module '{create_dto.title}' already exists in subject {create_dto.subject_id}",
                        existing_module_id=existing.id,
                    )
            raise ModuleIntegrityErrorRepository(str(e))

    def get_by_id(self, module_id: int) -> SubjectModuleRepositoryDTO:
        """Get module by ID"""
        instance = self._session.get(SubjectModule, module_id)
        if not instance:
            raise SubjectModuleNotFoundRepository(f"Module with id {module_id} not found")
        return SubjectModuleRepositoryDTO.model_validate(instance)

    def update(self, module_id: int, update_dto: SubjectModuleUpdateRepositoryDTO) -> SubjectModuleRepositoryDTO:
        """Update module by ID"""
        instance = self._session.get(SubjectModule, module_id)
        if not instance:
            raise SubjectModuleNotFoundRepository(f"Module with id {module_id} not found")

        update_data = update_dto.model_dump(exclude_unset=True)

        # Check for duplicate name if title is being updated
        if "title" in update_data:
            existing = self._session.execute(
                select(SubjectModule).where(
                    SubjectModule.subject_id == instance.subject_id,
                    SubjectModule.title == update_data["title"],
                    SubjectModule.id != module_id,
                )
            ).scalar_one_or_none()
            if existing:
                raise ModuleSameNameRepository(
                    f"Module '{update_data['title']}' already exists in subject {instance.subject_id}",
                    existing_module_id=existing.id,
                )

        for key, value in update_data.items():
            setattr(instance, key, value)

        try:
            self._session.flush()
            return SubjectModuleRepositoryDTO.model_validate(instance)
        except IntegrityError as e:
            raise ModuleIntegrityErrorRepository(str(e))

    def delete(self, module_id: int) -> None:
        """Delete module by ID"""
        instance = self._session.get(SubjectModule, module_id)
        if not instance:
            raise SubjectModuleNotFoundRepository(f"Module with id {module_id} not found")

        self._session.delete(instance)

        try:
            self._session.flush()
        except IntegrityError:
            raise ModuleIdViolatesNotNullRepository(f"Cannot delete module {module_id} due to foreign key constraints")

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
    ) -> tuple[list[SubjectModuleRepositoryDTO], int]:
        """Get paginated list of modules"""
        query = select(SubjectModule)

        if search:
            query = query.where(SubjectModule.title.ilike(f"%{search}%"))

        if sort_columns and is_sort_ascendings:
            order_by_clauses = []
            for i, column in enumerate(sort_columns):
                if i < len(is_sort_ascendings) and hasattr(SubjectModule, column):
                    attr = getattr(SubjectModule, column)
                    order_by_clauses.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_by_clauses:
                query = query.order_by(*order_by_clauses)
        else:
            query = query.join(Subject, Subject.id == SubjectModule.subject_id).order_by(
                SubjectModule.subject_id.asc(),
                SubjectModule.order_index.asc(),
                SubjectModule.created_at.asc(),
            )

        count_query = select(func.count()).select_from(query.subquery())
        total_count = self._session.execute(count_query).scalar()

        query = query.offset(offset).limit(limit)

        results = self._session.execute(query).scalars().all()

        module_dtos = []
        for module in results:
            lesson_count = self.count_lessons(module.id)

            # print(
            #     f"Module ID: {module.id}, Description: {module.description}, Lesson Count: {lesson_count}"
            # )

            module_dto = SubjectModuleRepositoryDTO(
                id=module.id,
                guid=module.guid,
                subject_id=module.subject_id,
                title=module.title,
                description=module.description,
                order_index=module.order_index,
                is_active=module.is_active,
                created_at=module.created_at,
                updated_at=module.updated_at,
                lesson_count=lesson_count,
            )
            module_dtos.append(module_dto)

        return module_dtos, total_count

    def get_by_subject(
        self,
        subject_id: int,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
    ) -> tuple[builtins.list[SubjectModuleRepositoryDTO], int]:
        """Get modules by subject ID"""
        query = select(SubjectModule).where(SubjectModule.subject_id == subject_id)

        if search:
            query = query.where(SubjectModule.title.ilike(f"%{search}%"))

        # Apply sorting
        if sort_columns and is_sort_ascendings:
            order_by_clauses = []
            for i, column in enumerate(sort_columns):
                if i < len(is_sort_ascendings) and hasattr(SubjectModule, column):
                    attr = getattr(SubjectModule, column)
                    order_by_clauses.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_by_clauses:
                query = query.order_by(*order_by_clauses)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_count = self._session.execute(count_query).scalar()

        # Apply pagination
        query = query.offset(offset).limit(limit)

        results = self._session.execute(query).scalars().all()
        module_dtos = []
        for module in results:
            lesson_count = self.count_lessons(module.id)
            module_dto = SubjectModuleRepositoryDTO(
                id=module.id,
                guid=module.guid,
                subject_id=module.subject_id,
                title=module.title,
                description=module.description,
                order_index=module.order_index,
                is_active=module.is_active,
                created_at=module.created_at,
                updated_at=module.updated_at,
                lesson_count=lesson_count,
            )
            module_dtos.append(module_dto)

        return module_dtos, total_count

    def count_lessons(self, module_id: int) -> int:
        """Count lessons in module"""
        return self._session.query(func.count(ModuleLesson.id)).filter(ModuleLesson.module_id == module_id).scalar()

    # def get_with_lessons(
    #     self, module_id: int
    # ) -> tuple[SubjectModuleRepositoryDTO, builtins.list[ModuleLessonRepositoryDTO]]:
    #     """Get module with its lessons"""
    #     module = self.get_by_id(module_id)

    #     lessons_query = (
    #         select(ModuleLesson).where(ModuleLesson.module_id == module_id).order_by(ModuleLesson.order_index)
    #     )
    #     lessons = self._session.execute(lessons_query).scalars().all()

    #     lesson_dtos = [ModuleLessonRepositoryDTO.model_validate(lesson) for lesson in lessons]

    #     return module, lesson_dtos

    def update_order(self, subject_id: int, module_orders: builtins.list[dict[str, int]]) -> None:
        """Обновить порядок модулей в предмете"""
        # Проверяем, что все модули принадлежат предмету
        module_ids = [order["id"] for order in module_orders]

        modules = (
            self._session.execute(
                select(SubjectModule).where(
                    SubjectModule.id.in_(module_ids),
                    SubjectModule.subject_id == subject_id,
                )
            )
            .scalars()
            .all()
        )

        if len(modules) != len(module_ids):
            raise ModuleOrderUpdateError("Некоторые модули не принадлежат указанному предмету или не найдены")

        # Обновляем порядок
        for order_data in module_orders:
            module = next((m for m in modules if m.id == order_data["id"]), None)
            if module:
                module.order_index = order_data["order_index"]

        try:
            self._session.flush()
        except Exception as e:
            self._session.rollback()
            raise ModuleOrderUpdateError(f"Ошибка обновления порядка: {str(e)}") from e

    def get_with_test_info(self, module_id: int) -> SubjectModule:
        """Получить модуль с информацией о тесте"""
        module = self._session.get(SubjectModule, module_id)
        if not module:
            raise SubjectModuleNotFoundRepository(f"Module with id {module_id} not found")
        return module

    def get_lessons_count_by_modules(self, module_ids: builtins.list[int]) -> dict[int, int]:
        """Get lesson count for each module"""
        if not module_ids:
            return {}

        query = (
            select(
                ModuleLesson.module_id,
                func.count(ModuleLesson.id).label("lesson_count"),
            )
            .where(ModuleLesson.module_id.in_(module_ids))
            .group_by(ModuleLesson.module_id)
        )

        result = self._session.execute(query).all()
        return {row.module_id: row.lesson_count for row in result}

    def reorder_after_delete(self, subject_id: int, deleted_order: int) -> None:
        """After deleting a module, decrement order_index of all modules with order > deleted_order by 1"""
        stmt = (
            update(SubjectModule)
            .where(SubjectModule.subject_id == subject_id)
            .where(SubjectModule.order_index > deleted_order)
            .values(order_index=SubjectModule.order_index - 1)
        )
        self._session.execute(stmt)

    def shift_right_for_insert(self, subject_id: int, from_order: int) -> None:
        """Shift all modules with order_index >= from_order to the right by 1"""
        stmt = (
            update(SubjectModule)
            .where(SubjectModule.subject_id == subject_id)
            .where(SubjectModule.order_index >= from_order)
            .values(order_index=SubjectModule.order_index + 1)
        )
        self._session.execute(stmt)
        logger.info(
            "shift_right_for_insert: subject_id=%s, from_order=%s",
            subject_id,
            from_order,
        )

    def shift_for_update(self, subject_id: int, old_order: int, new_order: int) -> None:
        """Reorder modules when a module's order_index changes from old_order to new_order"""
        if old_order == new_order:
            return
        if old_order < new_order:
            stmt = (
                update(SubjectModule)
                .where(SubjectModule.subject_id == subject_id)
                .where(SubjectModule.order_index > old_order)
                .where(SubjectModule.order_index <= new_order)
                .values(order_index=SubjectModule.order_index - 1)
            )
        else:
            stmt = (
                update(SubjectModule)
                .where(SubjectModule.subject_id == subject_id)
                .where(SubjectModule.order_index >= new_order)
                .where(SubjectModule.order_index < old_order)
                .values(order_index=SubjectModule.order_index + 1)
            )
        self._session.execute(stmt)
        logger.info(
            "shift_for_update: subject_id=%s, old=%s, new=%s",
            subject_id,
            old_order,
            new_order,
        )


# ========== Module Lesson Repository ==========


class ModuleLessonRepositoryInterface(
    BaseRepositoryInterface[
        ModuleLessonCreateRepositoryDTO,
        ModuleLessonUpdateRepositoryDTO,
        ModuleLessonRepositoryDTO,
    ]
):
    """Interface for module lesson data access operations"""

    def get_by_module(
        self,
        module_id: int,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[ModuleLessonRepositoryDTO], int]:
        """Get lessons by module ID"""
        raise NotImplementedError

    def get_by_topic(self, topic_id: int) -> list[ModuleLessonRepositoryDTO]:
        """Get lessons by topic ID"""
        raise NotImplementedError


class ModuleLessonRepository(ModuleLessonRepositoryInterface):
    """Implementation of module lesson data access operations"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: ModuleLessonCreateRepositoryDTO) -> ModuleLessonRepositoryDTO:
        """Create a new module lesson"""
        # Check if module exists
        module = self._session.get(SubjectModule, create_dto.module_id)
        if not module:
            raise SubjectModuleNotFoundRepository(f"Module with id {create_dto.module_id} not found")

        # Check if topic exists (if provided)
        if create_dto.topic_id:
            topic = self._session.get(Topic, create_dto.topic_id)
            if not topic:
                raise TopicNotFoundRepository(f"Topic with id {create_dto.topic_id} not found")

        instance = ModuleLesson(**create_dto.model_dump())
        self._session.add(instance)

        try:
            self._session.flush()
            return ModuleLessonRepositoryDTO.model_validate(instance)
        except IntegrityError as e:
            if "module_lessons_title_module_id_key" in str(e):
                # Check for duplicate name in module
                existing = self._session.execute(
                    select(ModuleLesson).where(
                        ModuleLesson.module_id == create_dto.module_id,
                        ModuleLesson.title == create_dto.title,
                    )
                ).scalar_one_or_none()
                if existing:
                    raise LessonSameNameRepository(
                        f"Lesson '{create_dto.title}' already exists in module {create_dto.module_id}",
                        existing_lesson_id=existing.id,
                    )
            raise LessonIntegrityErrorRepository(str(e))

    def get_by_id(self, lesson_id: int) -> ModuleLessonRepositoryDTO:
        """Get lesson by ID"""
        instance = self._session.get(ModuleLesson, lesson_id)
        if not instance:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")
        return ModuleLessonRepositoryDTO.model_validate(instance)

    def update(self, lesson_id: int, update_dto: ModuleLessonUpdateRepositoryDTO) -> ModuleLessonRepositoryDTO:
        """Update lesson by ID"""
        instance = self._session.get(ModuleLesson, lesson_id)
        if not instance:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")

        update_data = update_dto.model_dump(exclude_unset=True)

        # Check for duplicate name if title is being updated
        if "title" in update_data:
            existing = self._session.execute(
                select(ModuleLesson).where(
                    ModuleLesson.module_id == instance.module_id,
                    ModuleLesson.title == update_data["title"],
                    ModuleLesson.id != lesson_id,
                )
            ).scalar_one_or_none()
            if existing:
                raise LessonSameNameRepository(
                    f"Lesson '{update_data['title']}' already exists in module {instance.module_id}",
                    existing_lesson_id=existing.id,
                )

        for key, value in update_data.items():
            setattr(instance, key, value)

        try:
            self._session.flush()
            return ModuleLessonRepositoryDTO.model_validate(instance)
        except IntegrityError as e:
            raise LessonIntegrityErrorRepository(str(e))

    def delete(self, lesson_id: int) -> None:
        """Delete lesson by ID"""
        instance = self._session.get(ModuleLesson, lesson_id)
        if not instance:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")

        self._session.delete(instance)

        try:
            self._session.flush()
        except IntegrityError:
            raise LessonIdViolatesNotNullRepository(f"Cannot delete lesson {lesson_id} due to foreign key constraints")

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: list[str] | None = None,
        is_sort_ascendings: list[bool] | None = None,
    ) -> tuple[list[ModuleLessonRepositoryDTO], int]:
        """Get paginated list of lessons"""
        query = select(ModuleLesson)

        if search:
            query = query.where(ModuleLesson.title.ilike(f"%{search}%"))

        # Apply sorting
        if sort_columns and is_sort_ascendings:
            order_by_clauses = []
            for i, column in enumerate(sort_columns):
                if i < len(is_sort_ascendings) and hasattr(ModuleLesson, column):
                    attr = getattr(ModuleLesson, column)
                    order_by_clauses.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_by_clauses:
                query = query.order_by(*order_by_clauses)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_count = self._session.execute(count_query).scalar()

        # Apply pagination
        query = query.offset(offset).limit(limit)

        results = self._session.execute(query).scalars().all()
        return [ModuleLessonRepositoryDTO.model_validate(r) for r in results], total_count

    def get_by_module(
        self,
        module_id: int,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort_columns: builtins.list[str] | None = None,
        is_sort_ascendings: builtins.list[bool] | None = None,
    ) -> tuple[builtins.list[ModuleLessonRepositoryDTO], int]:
        """Get lessons by module ID"""
        query = select(ModuleLesson).where(ModuleLesson.module_id == module_id)

        if search:
            query = query.where(ModuleLesson.title.ilike(f"%{search}%"))

        # Apply sorting
        if sort_columns and is_sort_ascendings:
            order_by_clauses = []
            for i, column in enumerate(sort_columns):
                if i < len(is_sort_ascendings) and hasattr(ModuleLesson, column):
                    attr = getattr(ModuleLesson, column)
                    order_by_clauses.append(attr.asc() if is_sort_ascendings[i] else attr.desc())
            if order_by_clauses:
                query = query.order_by(*order_by_clauses)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_count = self._session.execute(count_query).scalar()

        # Apply pagination
        query = query.offset(offset).limit(limit)

        results = self._session.execute(query).scalars().all()
        return [ModuleLessonRepositoryDTO.model_validate(r) for r in results], total_count

    def get_by_topic(self, topic_id: int) -> builtins.list[ModuleLessonRepositoryDTO]:
        """Get lessons by topic ID"""
        query = select(ModuleLesson).where(ModuleLesson.topic_id == topic_id)
        results = self._session.execute(query).scalars().all()
        return [ModuleLessonRepositoryDTO.model_validate(r) for r in results]

    def update_order(self, module_id: int, lesson_orders: builtins.list[dict[str, int]]) -> None:
        """Обновить порядок уроков в модуле"""
        # Проверяем, что все уроки принадлежат модулю
        lesson_ids = [order["id"] for order in lesson_orders]

        lessons = (
            self._session.execute(
                select(ModuleLesson).where(ModuleLesson.id.in_(lesson_ids), ModuleLesson.module_id == module_id)
            )
            .scalars()
            .all()
        )

        if len(lessons) != len(lesson_ids):
            raise LessonOrderUpdateError("Some lessons do not belong to the module or are not found")

        for order_data in lesson_orders:
            lesson = next((lesson for lesson in lessons if lesson.id == order_data["id"]), None)
            if lesson:
                lesson.order_index = order_data["order_index"]

        try:
            self._session.flush()
        except Exception as e:
            self._session.rollback()
            raise LessonOrderUpdateError(f"Error updating lesson order: {str(e)}")

    def update_media(
        self,
        lesson_id: int,
        video_url: str | None = None,
        presentation_url: str | None = None,
    ) -> ModuleLessonRepositoryDTO:
        """Обновить медиа-файлы урока"""
        lesson = self._session.get(ModuleLesson, lesson_id)
        if not lesson:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")

        if video_url is not None:
            lesson.video_url = video_url
        if presentation_url is not None:
            lesson.presentation_url = presentation_url

        self._session.flush()
        return ModuleLessonRepositoryDTO.model_validate(lesson)

    def publish_lesson(
        self,
        lesson_id: int,
        is_published: bool,
        published_at: datetime | None = None,
    ) -> ModuleLessonRepositoryDTO:
        """Опубликовать или снять урок"""
        lesson = self._session.get(ModuleLesson, lesson_id)
        if not lesson:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")

        lesson.is_published = is_published
        if is_published and published_at:
            lesson.published_at = published_at
        elif not is_published:
            lesson.published_at = None

        self._session.flush()
        return ModuleLessonRepositoryDTO.model_validate(lesson)

    def get_with_test_info(self, lesson_id: int) -> ModuleLesson:
        """Получить урок с информацией о тесте"""
        lesson = self._session.get(ModuleLesson, lesson_id)
        if not lesson:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {lesson_id} not found")
        return lesson


# ========== Lesson Test Repository ==========


class LessonTestRepository:
    """Repository for lesson tests"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: LessonTestCreateRepositoryDTO) -> LessonTestRepositoryDTO:
        """Create a new lesson test"""
        # Check if lesson exists
        lesson = self._session.get(ModuleLesson, create_dto.lesson_id)
        if not lesson:
            raise ModuleLessonNotFoundRepository(f"Lesson with id {create_dto.lesson_id} not found")

        instance = LessonTest(**create_dto.model_dump())
        self._session.add(instance)
        self._session.flush()
        return LessonTestRepositoryDTO.model_validate(instance)

    def get_by_id(self, test_id: int) -> LessonTestRepositoryDTO:
        """Get lesson test by ID"""
        instance = self._session.get(LessonTest, test_id)
        if not instance:
            raise LessonTestNotFoundRepository(f"Lesson test with id {test_id} not found")
        return LessonTestRepositoryDTO.model_validate(instance)

    def get_by_lesson_id(self, lesson_id: int) -> LessonTestRepositoryDTO:
        """Get lesson test by lesson ID"""
        instance = self._session.query(LessonTest).filter(LessonTest.lesson_id == lesson_id).first()
        if not instance:
            raise LessonTestNotFoundRepository(f"Lesson test for lesson {lesson_id} not found")
        return LessonTestRepositoryDTO.model_validate(instance)

    def update(self, test_id: int, update_dto: LessonTestUpdateRepositoryDTO) -> LessonTestRepositoryDTO:
        """Update lesson test by ID"""
        instance = self._session.get(LessonTest, test_id)
        if not instance:
            raise LessonTestNotFoundRepository(f"Lesson test with id {test_id} not found")

        update_data = update_dto.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(instance, key, value)

        self._session.flush()
        return LessonTestRepositoryDTO.model_validate(instance)

    def delete(self, test_id: int) -> None:
        """Delete lesson test by ID"""
        instance = self._session.get(LessonTest, test_id)
        if not instance:
            raise LessonTestNotFoundRepository(f"Lesson test with id {test_id} not found")

        self._session.delete(instance)

    def add_questions(self, test_id: int, question_ids: list[int]) -> list[LessonTestQuestion]:
        """Добавить вопросы в тест урока"""
        test = self._session.get(LessonTest, test_id)
        if not test:
            raise LessonTestNotFoundRepository(f"Lesson test with id {test_id} not found")

        # Проверяем существование вопросов
        existing_questions = (
            self._session.execute(select(Question).where(Question.id.in_(question_ids))).scalars().all()
        )

        if len(existing_questions) != len(question_ids):
            raise QuestionNotFoundError("Некоторые вопросы не найдены")

        # Проверяем, что вопросы не дублируются
        existing_test_questions = (
            self._session.execute(
                select(LessonTestQuestion).where(
                    LessonTestQuestion.lesson_test_id == test_id,
                    LessonTestQuestion.question_id.in_(question_ids),
                )
            )
            .scalars()
            .all()
        )

        if existing_test_questions:
            existing_ids = [q.question_id for q in existing_test_questions]
            raise TestQuestionAlreadyExistsError(f"Вопросы с ID {existing_ids} уже добавлены в тест")

        # Получаем максимальный order_index
        max_order = (
            self._session.execute(
                select(func.max(LessonTestQuestion.order_index)).where(LessonTestQuestion.lesson_test_id == test_id)
            ).scalar()
            or 0
        )

        # Добавляем вопросы
        added_questions = []
        for i, question_id in enumerate(question_ids):
            test_question = LessonTestQuestion(
                lesson_test_id=test_id,
                question_id=question_id,
                order_index=max_order + i + 1,
                points=1,
            )
            self._session.add(test_question)
            added_questions.append(test_question)

        self._session.flush()
        return added_questions

    def remove_question(self, test_id: int, question_id: int) -> None:
        """Удалить вопрос из теста урока"""
        test_question = self._session.execute(
            select(LessonTestQuestion).where(
                LessonTestQuestion.lesson_test_id == test_id,
                LessonTestQuestion.question_id == question_id,
            )
        ).scalar_one_or_none()

        if not test_question:
            raise QuestionNotFoundError(f"Question {question_id} not found in test {test_id}")

        self._session.delete(test_question)
        self._session.flush()

    def get_questions_count(self, test_id: int) -> int:
        """Получить количество вопросов в тесте"""
        return self._session.execute(
            select(func.count(LessonTestQuestion.id)).where(LessonTestQuestion.lesson_test_id == test_id)
        ).scalar()


# ========== Module Test Repository ==========


class ModuleTestRepository:
    """Repository for module tests"""

    def __init__(self, session: Session):
        self._session = session

    def create(self, create_dto: ModuleTestCreateRepositoryDTO) -> ModuleTestRepositoryDTO:
        """Create a new module test"""
        # Check if module exists
        module = self._session.get(SubjectModule, create_dto.module_id)
        if not module:
            raise SubjectModuleNotFoundRepository(f"Module with id {create_dto.module_id} not found")

        instance = ModuleTest(**create_dto.model_dump())
        self._session.add(instance)
        self._session.flush()
        return ModuleTestRepositoryDTO.model_validate(instance)

    def get_by_id(self, test_id: int) -> ModuleTestRepositoryDTO:
        """Get module test by ID"""
        instance = self._session.get(ModuleTest, test_id)
        if not instance:
            raise ModuleTestNotFoundRepository(f"Module test with id {test_id} not found")
        return ModuleTestRepositoryDTO.model_validate(instance)

    # def get_by_module_id(self, module_id: int) -> ModuleTestRepositoryDTO:
    #     """Get module test by module ID"""
    #     instance = (
    #         self._session.query(ModuleTest)
    #         .filter(ModuleTest.module_id == module_id)
    #         .first()
    #     )
    #     if not instance:
    #         raise ModuleTestNotFoundRepository(
    #             f"Module test for module {module_id} not found"
    #         )
    #     return ModuleTestRepositoryDTO.model_validate(instance)

    def update(self, test_id: int, update_dto: ModuleTestUpdateRepositoryDTO) -> ModuleTestRepositoryDTO:
        """Update module test by ID"""
        instance = self._session.get(ModuleTest, test_id)
        if not instance:
            raise ModuleTestNotFoundRepository(f"Module test with id {test_id} not found")

        update_data = update_dto.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(instance, key, value)

        self._session.flush()
        return ModuleTestRepositoryDTO.model_validate(instance)

    def delete(self, test_id: int) -> None:
        """Delete module test by ID"""
        instance = self._session.get(ModuleTest, test_id)
        if not instance:
            raise ModuleTestNotFoundRepository(f"Module test with id {test_id} not found")

        self._session.delete(instance)

    def add_questions(self, test_id: int, question_ids: list[int]) -> list["ModuleTestQuestion"]:
        """Добавить вопросы в тест модуля"""
        test = self._session.get(ModuleTest, test_id)
        if not test:
            raise ModuleTestNotFoundRepository(f"Module test with id {test_id} not found")

        # Проверяем существование вопросов
        existing_questions = (
            self._session.execute(select(Question).where(Question.id.in_(question_ids))).scalars().all()
        )

        if len(existing_questions) != len(question_ids):
            raise QuestionNotFoundError("Некоторые вопросы не найдены")

        # Проверяем, что вопросы не дублируются
        existing_test_questions = (
            self._session.execute(
                select(ModuleTestQuestion).where(
                    ModuleTestQuestion.module_test_id == test_id,
                    ModuleTestQuestion.question_id.in_(question_ids),
                )
            )
            .scalars()
            .all()
        )

        if existing_test_questions:
            existing_ids = [q.question_id for q in existing_test_questions]
            raise TestQuestionAlreadyExistsError(f"Вопросы с ID {existing_ids} уже добавлены в тест")

        # Получаем максимальный order_index
        max_order = (
            self._session.execute(
                select(func.max(ModuleTestQuestion.order_index)).where(ModuleTestQuestion.module_test_id == test_id)
            ).scalar()
            or 0
        )

        # Добавляем вопросы
        added_questions = []
        for i, question_id in enumerate(question_ids):
            test_question = ModuleTestQuestion(
                module_test_id=test_id,
                question_id=question_id,
                order_index=max_order + i + 1,
                points=1,
            )
            self._session.add(test_question)
            added_questions.append(test_question)

        self._session.flush()
        return added_questions

    def remove_question(self, test_id: int, question_id: int) -> None:
        """Удалить вопрос из теста модуля"""
        test_question = self._session.execute(
            select(ModuleTestQuestion).where(
                ModuleTestQuestion.module_test_id == test_id,
                ModuleTestQuestion.question_id == question_id,
            )
        ).scalar_one_or_none()

        if not test_question:
            raise QuestionNotFoundError(f"Question {question_id} not found in test {test_id}")

        self._session.delete(test_question)
        self._session.flush()

    def get_questions_count(self, test_id: int) -> int:
        """Получить количество вопросов в тесте модуля"""
        return self._session.execute(
            select(func.count(ModuleTestQuestion.id)).where(ModuleTestQuestion.module_test_id == test_id)
        ).scalar()

    def get_by_module_id(self, module_id: int) -> ModuleTest | None:
        """Получить тест модуля по ID модуля (может вернуть None)"""
        return self._session.execute(select(ModuleTest).where(ModuleTest.module_id == module_id)).scalar_one_or_none()
