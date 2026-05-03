from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    allow_only_admins,
    get_module_lesson_service,
    get_subject_module_service,
)
from quiz.dtos.modules import (
    LessonOrderUpdateDTO,
    LessonWithTestInfoDTO,
    MediaUpdateDTO,
    ModuleLessonCreateDTO,
    ModuleLessonDTO,
    ModuleLessonServiceDTO,
    ModuleLessonUpdateDTO,
    ModuleOrderUpdateDTO,
    ModuleTestCreateServiceDTO,
    ModuleTestQuestionAddDTO,
    ModuleTestServiceDTO,
    ModuleTestUpdateServiceDTO,
    ModuleWithTestInfoDTO,
    PublishLessonDTO,
    SubjectModuleCreateDTO,
    SubjectModuleDTO,
    SubjectModuleUpdateDTO,
)
from quiz.services.modules import ModuleLessonService, SubjectModuleService

router = APIRouter(
    prefix="/admin/modules",
    tags=["Admin - Modules"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get(
    "",
    response_model=list[SubjectModuleDTO],
    summary="Get all modules",
    description="Get all modules with pagination, search, and sorting options",
)
async def get_modules(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str | None = "subject_id, order_index, created_at",
    sort_order: str | None = "desc",
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get all modules with pagination, search, and sorting options"""
    modules, _ = module_service.list(
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return modules


@router.post(
    "",
    response_model=SubjectModuleDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new module",
    description="Create a new module with the provided data",
)
async def create_module(
    module_data: SubjectModuleCreateDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Create a new module"""
    try:
        return module_service.create(module_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/subject/{subject_id}",
    response_model=list[SubjectModuleDTO],
    summary="Get modules by subject",
    description="Get modules by subject ID",
)
async def get_modules_by_subject(
    subject_id: int,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str | None = "order_index",
    sort_order: str | None = "asc",
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get modules by subject ID"""
    modules, _ = module_service.get_by_subject(
        subject_id=subject_id,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return modules


@router.patch(
    "/subject/{subject_id}/order",
    summary="Update module order",
    description="Update the order of modules in a subject",
)
async def update_module_order(
    subject_id: int,
    order_data: ModuleOrderUpdateDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Update module order"""
    try:
        module_service.update_module_order(subject_id, order_data.module_orders)
        return {"message": "Module order updated successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/lessons",
    response_model=list[ModuleLessonDTO],
    summary="Get all lessons",
    description="Get list of all lessons",
)
async def get_lessons(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str | None = "created_at",
    sort_order: str | None = "desc",
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Get all lessons"""
    lessons, _ = lesson_service.list(
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return lessons


@router.post(
    "/lessons",
    response_model=ModuleLessonDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lesson",
    description="Create a new lesson with the provided data",
)
async def create_lesson(
    lesson_data: ModuleLessonCreateDTO,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Create a new lesson"""
    try:
        return lesson_service.create(lesson_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/lessons/{lesson_id}",
    response_model=ModuleLessonDTO,
    summary="Get lesson by ID",
    description="Get lesson by ID",
)
async def get_lesson(
    lesson_id: int,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Get lesson by ID"""
    try:
        return lesson_service.get_by_id(lesson_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.patch(
    "/lessons/{lesson_id}",
    response_model=ModuleLessonDTO,
    summary="Update lesson",
    description="Update lesson with the provided data",
)
async def update_lesson(
    lesson_id: int,
    lesson_data: ModuleLessonUpdateDTO,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Update lesson"""
    try:
        return lesson_service.update(lesson_id, lesson_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete(
    "/lessons/{lesson_id}",
    summary="Delete lesson",
    description="Delete lesson by ID",
)
async def delete_lesson(
    lesson_id: int,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Delete lesson by ID"""
    try:
        lesson_service.delete(lesson_id)
        return {"message": "Lesson deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/lessons/{lesson_id}/with-test-info",
    response_model=LessonWithTestInfoDTO,
    summary="Get lesson with test info",
    description="Get lesson with test info (trainer info)",
)
async def get_lesson_with_test_info(
    lesson_id: int,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Get lesson with test info"""
    try:
        return lesson_service.get_lesson_with_test_info(lesson_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.patch(
    "/lessons/{lesson_id}/media",
    response_model=ModuleLessonServiceDTO,
    summary="Update lesson media files",
    description="Update video and presentation files for a lesson",
)
async def update_lesson_media(
    lesson_id: int,
    media_data: MediaUpdateDTO,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Update lesson media files"""
    try:
        return lesson_service.update_lesson_media(
            lesson_id,
            video_url=media_data.video_url,
            presentation_url=media_data.presentation_url,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/lessons/{lesson_id}/publish",
    response_model=ModuleLessonServiceDTO,
    summary="Publish lesson",
    description="Publish lesson (makes it available to users)",
)
async def publish_lesson(
    lesson_id: int,
    publish_data: PublishLessonDTO,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Publish lesson"""
    try:
        return lesson_service.publish_lesson(
            lesson_id,
            is_published=publish_data.is_published,
            published_at=publish_data.published_at,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{module_id}",
    response_model=SubjectModuleDTO,
    summary="Get module by ID",
    description="Get module by ID",
)
async def get_module(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get module by ID"""
    try:
        return module_service.get_by_id(module_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.patch(
    "/{module_id}",
    response_model=SubjectModuleDTO,
    summary="Update module",
    description="Update module",
)
async def update_module(
    module_id: int,
    module_data: SubjectModuleUpdateDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Update module"""
    try:
        return module_service.update(module_id, module_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete(
    "/{module_id}",
    summary="Delete module",
    description="Delete module",
)
async def delete_module(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Delete module"""
    try:
        module_service.delete(module_id)
        return {"message": "Module deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{module_id}/with-test-info",
    response_model=ModuleWithTestInfoDTO,
    summary="Get module with test info",
    description="Get module with information about test presence and parameters",
)
async def get_module_with_test_info(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get module with test info"""
    try:
        return module_service.get_module_with_test_info(module_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{module_id}/lessons",
    response_model=list[ModuleLessonDTO],
    summary="Get module lessons",
    description="Get lessons by module ID",
)
async def get_module_lessons_admin(
    module_id: int,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str | None = "order_index",
    sort_order: str | None = "asc",
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Get module lessons"""
    lessons, _ = lesson_service.get_by_module(
        module_id=module_id,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return lessons


@router.patch(
    "/{module_id}/lessons/order",
    summary="Update lesson order",
    description="Update lesson order in module",
)
async def update_lesson_order(
    module_id: int,
    order_data: LessonOrderUpdateDTO,
    lesson_service: ModuleLessonService = Depends(get_module_lesson_service),
):
    """Update lesson order in module"""
    try:
        lesson_service.update_lesson_order(module_id, order_data.lesson_orders)
        return {"message": "Lesson order updated successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/{module_id}/test",
    response_model=ModuleTestServiceDTO,
    summary="Get module test",
    description="Get module test by module ID",
)
async def get_module_test(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Get module test"""
    try:
        return module_service.get_module_test(module_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/{module_id}/test",
    response_model=ModuleTestServiceDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Create module test",
    description="Create final test for module",
)
async def create_module_test(
    module_id: int,
    test_data: ModuleTestCreateServiceDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Create module test"""
    try:
        return module_service.create_module_test(module_id, test_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.patch(
    "/{module_id}/test",
    response_model=ModuleTestServiceDTO,
    summary="Update module test",
    description="Update module test",
)
async def update_module_test(
    module_id: int,
    test_data: ModuleTestUpdateServiceDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Update module test"""
    try:
        return module_service.update_module_test(module_id, test_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete(
    "/{module_id}/test",
    summary="Delete module test",
    description="Delete module test",
)
async def delete_module_test(
    module_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Delete module test"""
    try:
        module_service.delete_module_test(module_id)
        return {"message": "Module test deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/{module_id}/test/questions",
    summary="Add questions to module test",
    description="Adding questions to module test",
)
async def add_questions_to_module_test(
    module_id: int,
    question_data: ModuleTestQuestionAddDTO,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Add questions to module test"""
    try:
        module_service.add_questions_to_module_test(module_id, question_data.question_ids)
        return {"message": f"Added {len(question_data.question_ids)} questions to module test"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete(
    "/{module_id}/test/questions/{question_id}",
    summary="Delete question from module test",
    description="Delete question from module test",
)
async def remove_question_from_module_test(
    module_id: int,
    question_id: int,
    module_service: SubjectModuleService = Depends(get_subject_module_service),
):
    """Delete question from module test"""
    try:
        module_service.remove_question_from_module_test(module_id, question_id)
        return {"message": f"Removed question {question_id} from module test"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
