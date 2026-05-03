from uuid import UUID

from sqlalchemy.orm import Session

from quiz.dtos.modules import UserLessonProgressDTO, UserModuleProgressDTO
from quiz.models.modular_edu import UserLessonProgress, UserModuleProgress


class UserLessonProgressRepository:
    """Репозиторий для прогресса уроков пользователя"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_lesson_and_user(self, lesson_id: int, user_id: UUID) -> UserLessonProgressDTO | None:
        """Получить прогресс пользователя по уроку"""
        progress = (
            self._session.query(UserLessonProgress)
            .filter(
                UserLessonProgress.lesson_id == lesson_id,
                UserLessonProgress.student_guid == user_id,
            )
            .first()
        )
        if progress:
            return UserLessonProgressDTO.model_validate(progress)
        return None

    def update_or_create(self, progress_dto: UserLessonProgressDTO) -> UserLessonProgressDTO:
        """Обновить или создать запись прогресса урока"""
        progress = (
            self._session.query(UserLessonProgress)
            .filter(
                UserLessonProgress.lesson_id == progress_dto.lesson_id,
                UserLessonProgress.student_guid == progress_dto.student_guid,
            )
            .first()
        )

        if progress:
            update_data = progress_dto.model_dump(exclude={"id"})
            for key, value in update_data.items():
                setattr(progress, key, value)
        else:
            progress = UserLessonProgress(**progress_dto.model_dump(exclude={"id"}))
            self._session.add(progress)

        self._session.flush()
        return UserLessonProgressDTO.model_validate(progress)

    def create(self, data: dict) -> UserLessonProgressDTO:
        """
        Создать новую запись прогресса урока.
        Args:
            data: словарь с данными для создания (поля UserLessonProgressDTO без id)
        Returns:
            UserLessonProgressDTO созданной записи
        """
        dto = UserLessonProgressDTO(**data)
        return self.update_or_create(dto)

    # def count_accessed_in_range(self, student_guid: UUID, start: datetime, end: datetime) -> int:
    #     return (
    #         self._session.query(UserLessonProgress)
    #         .filter(
    #             UserLessonProgress.student_guid == student_guid,
    #             UserLessonProgress.last_accessed_at >= start,
    #             UserLessonProgress.last_accessed_at <= end,
    #         )
    #         .count()
    #     )


class UserModuleProgressRepository:
    """Репозиторий для прогресса модулей пользователя"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_module_and_user(self, module_id: int, user_id: UUID) -> UserModuleProgressDTO | None:
        """Получить прогресс пользователя по модулю"""
        progress = (
            self._session.query(UserModuleProgress)
            .filter(
                UserModuleProgress.module_id == module_id,
                UserModuleProgress.student_guid == user_id,
            )
            .first()
        )
        if progress:
            return UserModuleProgressDTO.model_validate(progress)
        return None

    def update_or_create(self, progress_dto: UserModuleProgressDTO) -> UserModuleProgressDTO:
        """Обновить или создать запись прогресса модуля"""
        progress = (
            self._session.query(UserModuleProgress)
            .filter(
                UserModuleProgress.module_id == progress_dto.module_id,
                UserModuleProgress.student_guid == progress_dto.student_guid,
            )
            .first()
        )

        if progress:
            update_data = progress_dto.model_dump(exclude={"id"})
            for key, value in update_data.items():
                setattr(progress, key, value)
        else:
            progress = UserModuleProgress(**progress_dto.model_dump(exclude={"id"}))
            self._session.add(progress)

        self._session.flush()
        return UserModuleProgressDTO.model_validate(progress)
