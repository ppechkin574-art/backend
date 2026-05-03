from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quiz.dtos.enums import Difficulty

# ========== Subject Module DTOs ==========


class SubjectModuleBaseDTO(BaseModel):
    title: str = Field(..., max_length=255)
    description: str
    order_index: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)


class SubjectModuleCreateServiceDTO(SubjectModuleBaseDTO):
    subject_id: int


class SubjectModuleCreateRepositoryDTO(SubjectModuleBaseDTO):
    subject_id: int


class SubjectModuleUpdateServiceDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    order_index: int | None = Field(None, ge=0)
    is_active: bool | None = None
    subject_id: int | None = None


class SubjectModuleUpdateRepositoryDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    order_index: int | None = Field(None, ge=0)
    is_active: bool | None = None
    subject_id: int | None = None


class SubjectModuleServiceDTO(SubjectModuleBaseDTO):
    id: int
    guid: UUID
    subject_id: int
    # subject_name: Optional[str] = None
    lesson_count: int | None = 0
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class SubjectModuleRepositoryDTO(SubjectModuleBaseDTO):
    id: int
    guid: UUID
    subject_id: int
    # subject_name: Optional[str] = None
    lesson_count: int | None = 0
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class SubjectModuleWithLessonsDTO(SubjectModuleServiceDTO):
    lessons: list["ModuleLessonServiceDTO"] = []
    total_lessons: int = 0
    completed_lessons: int = 0
    progress_percentage: float = 0.0
    has_module_test: bool = False
    is_completed: bool = False


# ========== Module Lesson DTOs ==========


class ModuleLessonBaseDTO(BaseModel):
    title: str = Field(..., max_length=255)
    description: str
    video_url: str | None = Field(None, max_length=500)
    presentation_url: str | None = Field(None, max_length=500)
    order_index: int = Field(default=0, ge=0)
    difficulty: Difficulty | None = None
    is_published: bool = Field(default=False)
    published_at: datetime | None = None


class ModuleLessonCreateServiceDTO(ModuleLessonBaseDTO):
    module_id: int
    topic_id: int | None = None


class ModuleLessonCreateRepositoryDTO(ModuleLessonBaseDTO):
    module_id: int
    topic_id: int | None = None


class ModuleLessonUpdateServiceDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    video_url: str | None = Field(None, max_length=500)
    presentation_url: str | None = Field(None, max_length=500)
    order_index: int | None = Field(None, ge=0)
    difficulty: Difficulty | None = None
    is_published: bool | None = None
    published_at: datetime | None = None
    module_id: int | None = None
    topic_id: int | None = None


class ModuleLessonUpdateRepositoryDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    video_url: str | None = Field(None, max_length=500)
    presentation_url: str | None = Field(None, max_length=500)
    order_index: int | None = Field(None, ge=0)
    difficulty: Difficulty | None = None
    is_published: bool | None = None
    published_at: datetime | None = None
    module_id: int | None = None
    topic_id: int | None = None


class ModuleLessonServiceDTO(ModuleLessonBaseDTO):
    id: int
    guid: UUID
    module_id: int
    topic_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ModuleLessonRepositoryDTO(ModuleLessonBaseDTO):
    id: int
    guid: UUID
    module_id: int
    topic_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ModuleLessonWithDetailsDTO(ModuleLessonServiceDTO):
    module_title: str | None = None
    subject_name: str | None = None
    topic_name: str | None = None
    has_test: bool = False
    is_linked_to_topic: bool = False
    trainer_id: int | None = None
    lesson_test_id: int | None = None
    trainer_last_attempt_id: int | None = None


# ========== Lesson Test DTOs ==========


class LessonTestBaseDTO(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    pass_score_percentage: int = Field(default=70, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    is_active: bool = Field(default=True)


class LessonTestCreateServiceDTO(LessonTestBaseDTO):
    lesson_id: int


class LessonTestCreateRepositoryDTO(LessonTestBaseDTO):
    lesson_id: int


class LessonTestUpdateServiceDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    pass_score_percentage: int | None = Field(None, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int | None = Field(None, ge=1)
    is_active: bool | None = None


class LessonTestUpdateRepositoryDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    pass_score_percentage: int | None = Field(None, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int | None = Field(None, ge=1)
    is_active: bool | None = None


class LessonTestServiceDTO(LessonTestBaseDTO):
    id: int
    guid: UUID
    lesson_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class LessonTestRepositoryDTO(LessonTestBaseDTO):
    id: int
    guid: UUID
    lesson_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# ========== Module Test DTOs ==========


class ModuleTestBaseDTO(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    pass_score_percentage: int = Field(default=70, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    is_active: bool = Field(default=True)


class ModuleTestCreateServiceDTO(ModuleTestBaseDTO):
    module_id: int


class ModuleTestCreateRepositoryDTO(ModuleTestBaseDTO):
    module_id: int


class ModuleTestUpdateServiceDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    pass_score_percentage: int | None = Field(None, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int | None = Field(None, ge=1)
    is_active: bool | None = None


class ModuleTestUpdateRepositoryDTO(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    pass_score_percentage: int | None = Field(None, ge=0, le=100)
    time_limit_minutes: int | None = Field(None, ge=1)
    max_attempts: int | None = Field(None, ge=1)
    is_active: bool | None = None


class ModuleTestServiceDTO(ModuleTestBaseDTO):
    id: int
    guid: UUID
    module_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ModuleTestRepositoryDTO(ModuleTestBaseDTO):
    id: int
    guid: UUID
    module_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# ========== Progress DTOs ==========


class UserLessonProgressDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    student_guid: UUID
    lesson_id: int
    completed_test: bool = False
    test_score: int = 0
    test_max_score: int = 0
    test_percentage: float = 0.0
    test_attempts_count: int = 0
    time_spent_seconds: int = 0
    is_completed: bool = False
    completed_at: datetime | None = None
    last_accessed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserModuleProgressDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    student_guid: UUID
    module_id: int
    completed_lessons_count: int = 0
    total_lessons_count: int = 0
    module_test_completed: bool = False
    module_test_score: int = 0
    module_test_max_score: int = 0
    module_test_percentage: float = 0.0
    module_test_attempts_count: int = 0
    is_completed: bool = False
    overall_progress_percentage: float = 0.0
    time_spent_seconds: int = 0
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ========== Request/Response DTOs ==========


class SubjectModuleListResponseDTO(BaseModel):
    count: int
    data: list[SubjectModuleServiceDTO]


class ModuleLessonListResponseDTO(BaseModel):
    count: int
    data: list[ModuleLessonServiceDTO]


SubjectModuleWithLessonsDTO.update_forward_refs()
SubjectModuleCreateDTO = SubjectModuleCreateServiceDTO
SubjectModuleUpdateDTO = SubjectModuleUpdateServiceDTO
SubjectModuleDTO = SubjectModuleServiceDTO

ModuleLessonCreateDTO = ModuleLessonCreateServiceDTO
ModuleLessonUpdateDTO = ModuleLessonUpdateServiceDTO
ModuleLessonDTO = ModuleLessonServiceDTO
ModuleLessonWithContentDTO = ModuleLessonWithDetailsDTO


class SubjectModuleWithProgressDTO(SubjectModuleDTO):
    total_lessons: int = 0
    completed_lessons: int = 0
    progress_percentage: float = 0.0
    is_completed: bool = False


class ModuleLessonWithProgressDTO(ModuleLessonDTO):
    progress: UserLessonProgressDTO | None = None
    is_started: bool = False
    is_completed: bool = False


class SubjectWithModulesDTO(BaseModel):
    id: int
    name: str
    modules: list[SubjectModuleWithProgressDTO] = []
    total_modules: int = 0
    completed_modules: int = 0
    overall_progress: float = 0.0


class ModuleProgressSummaryDTO(BaseModel):
    module_id: int
    module_title: str
    total_lessons: int
    completed_lessons: int
    progress_percentage: float
    time_spent_minutes: int
    is_completed: bool
    last_accessed_at: datetime | None = None


class SubjectProgressDTO(BaseModel):
    subject_id: int
    subject_name: str
    total_modules: int
    completed_modules: int
    total_lessons: int
    completed_lessons: int
    overall_progress: float
    total_time_spent_minutes: int
    modules_progress: list[ModuleProgressSummaryDTO] = []


class LessonProgressUpdateDTO(BaseModel):
    watched_video: bool | None = None
    viewed_presentation: bool | None = None
    read_content: bool | None = None
    test_score: int | None = None
    test_max_score: int | None = None
    completed_test: bool | None = None
    time_spent_seconds: int = 0


class ModuleLessonWithTrainerDTO(ModuleLessonServiceDTO):
    progress: UserLessonProgressDTO | None = None
    is_started: bool = False
    is_completed: bool = False
    trainer_id: int | None = None
    topic_name: str | None = None


class LessonProgressShortDTO(BaseModel):
    completed_test: bool = False
    test_score: int = 0
    test_max_score: int = 0
    test_percentage: float = 0.0
    test_attempts_count: int = 0
    time_spent_seconds: int = 0


class ModuleLessonShortDTO(BaseModel):
    id: int
    name: str
    topic_id: int | None = None
    trainer_id: int | None = None
    start_score: int = Field(default=0)
    with_materials: bool = Field(default=True)
    is_completed: bool = False
    test_result: float | None = Field(None, ge=0, le=1)


class ModuleLessonResponseDTO(BaseModel):
    title: str
    description: str
    video_url: str | None = None
    presentation_url: str | None = None
    topic_id: int | None = None
    trainer_id: int | None = None
    progress: LessonProgressShortDTO
    is_completed: bool


class ModuleWithLessonsDTO(SubjectModuleServiceDTO):
    total_lessons: int = 0
    lessons: list[ModuleLessonShortDTO] = []
    completed_lessons: int = 0
    progress_percentage: float = 0.0
    is_completed: bool = False


class ModuleInSubjectResponseDTO(BaseModel):
    id: int
    title: str
    description: str
    total_lessons: int = 0
    lessons: list[ModuleLessonShortDTO] = []
    completed_lessons: int = 0
    progress_percentage: float = 0.0
    is_completed: bool = False


class SubjectModulesResponseDTO(BaseModel):
    id: int
    name: str
    modules: list[ModuleInSubjectResponseDTO] = []
    total_modules: int = 0
    completed_modules: int = 0
    overall_progress: float = 0.0


class LessonOrderUpdateDTO(BaseModel):
    lesson_orders: list[dict[str, int]] = Field(
        ...,
        description="Список словарей с id урока и новым order_index: [{'id': 1, 'order_index': 0}, ...]",
    )


class ModuleOrderUpdateDTO(BaseModel):
    module_orders: list[dict[str, int]] = Field(
        ...,
        description="Список словарей с id модуля и новым order_index: [{'id': 1, 'order_index': 0}, ...]",
    )


class LessonTestQuestionAddDTO(BaseModel):
    question_ids: list[int] = Field(..., description="Список ID вопросов для добавления в тест")


class ModuleTestQuestionAddDTO(BaseModel):
    question_ids: list[int] = Field(..., description="Список ID вопросов для добавления в тест")


class MediaUpdateDTO(BaseModel):
    video_url: str | None = Field(None, max_length=500)
    presentation_url: str | None = Field(None, max_length=500)


class PublishLessonDTO(BaseModel):
    is_published: bool
    published_at: datetime | None = None


class LessonWithTestInfoDTO(ModuleLessonServiceDTO):
    has_test: bool = False
    test_id: int | None = None
    test_title: str | None = None
    questions_count: int = 0


class ModuleWithTestInfoDTO(SubjectModuleServiceDTO):
    has_module_test: bool = False
    module_test_id: int | None = None
    module_test_title: str | None = None
    module_test_questions_count: int = 0
