from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.common import ListDTO, ListQueryDTO
from api.dependencies import allow_only_admins, get_subject_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import (
    to_subject_create_service,
    to_subject_update_service,
)
from api.routes.quiz.dtos import ImageResponse, SubjectCreateDTO, SubjectUpdateDTO
from quiz.dtos.subject import (
    SubjectServiceDTO,
    SubjectUpdateServiceDTO,
    SubjectWithStatsDTO,
)
from quiz.exceptions import (
    SubjectAlreadyExists,
    SubjectIdViolatesNotNullService,
    SubjectIntegrityErrorService,
    SubjectNotFoundService,
)
from quiz.services.subjects import SubjectServiceInterface

router = APIRouter(
    prefix="/admin/subjects",
    tags=["Admin - Subjects"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get(
    "",
    response_model=ListDTO[SubjectServiceDTO],
    summary="Получить предметы",
    description="Возвращает список предметов с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFoundService),
    },
)
async def get_admin_subjects(
    query: ListQueryDTO = Depends(),
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    subjects, total_count = service.list(
        page=query.page,
        page_size=query.page_size,
        search=query.search,
        sort_by=query.sort_columns[0] if query.sort_columns else None,
        sort_order=("asc" if (query.is_sort_ascendings and query.is_sort_ascendings[0]) else "desc"),
    )

    return ListDTO[SubjectServiceDTO](
        draw=query.draw,
        records_total=total_count,
        records_filtered=total_count,
        data=subjects,
    )


@router.get(
    "/with-stats",
    response_model=list[SubjectWithStatsDTO],
    summary="Предметы со статистикой",
    description="Возвращает предметы со статистикой вопросов и тем",
    responses={
        **get_common_responses("read"),
    },
)
async def get_subjects_with_stats(
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    subjects_with_counts = service.get_with_question_counts()
    return [
        SubjectWithStatsDTO(
            id=item["subject"].id,
            name=item["subject"].name,
            type=item["subject"].type or None,
            image=item["subject"].image or None,
            topic_count=service.count_topics(item["subject"].id),
            question_count=item["question_count"],
        )
        for item in subjects_with_counts
    ]


@router.get(
    "/{subject_id}",
    response_model=SubjectServiceDTO,
    summary="Получить предмет по ID",
    description="Возвращает детальную информацию о предмете",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFoundService),
    },
)
async def get_admin_subject_by_id(
    subject_id: int,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    if subject := service.get_by_id(subject_id):
        return subject
    else:
        raise HTTPException(status_code=404, detail="Subject not found")


@router.post(
    "",
    response_model=SubjectServiceDTO,
    status_code=201,
    summary="Создать предмет",
    description="Создание нового предмета",
    responses={
        **get_common_responses("create"),
        **get_error_responses(SubjectIntegrityErrorService, SubjectAlreadyExists),
    },
)
async def create_subject(
    subject_create: SubjectCreateDTO,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    return service.create(to_subject_create_service(subject_create))


@router.patch(
    "/{subject_id}",
    response_model=SubjectServiceDTO,
    summary="Обновить предмет",
    description="Частичное обновление предмета",
    responses={
        **get_common_responses("update"),
        **get_error_responses(SubjectNotFoundService, SubjectIntegrityErrorService),
    },
)
async def update_subject(
    subject_id: int,
    subject_update: SubjectUpdateDTO,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    return service.update(subject_id, to_subject_update_service(subject_update))


@router.delete(
    "/{subject_id}",
    summary="Удалить предмет",
    description="Удаление предмета",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(SubjectNotFoundService, SubjectIdViolatesNotNullService),
    },
)
async def delete_subject(
    subject_id: int,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    service.delete(subject_id)
    return {"message": "Subject deleted successfully"}


@router.get(
    "/{subject_id}/stats",
    summary="Статистика предмета",
    description="Возвращает детальную статистику по предмету",
    responses={
        **get_common_responses("read"),
        **get_error_responses(SubjectNotFoundService),
    },
)
async def get_subject_stats(
    subject_id: int,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    return service.get_detailed_stats(subject_id)


@router.post("/{subject_id}/image", response_model=ImageResponse)
async def upload_subject_image(
    subject_id: int,
    file: UploadFile = File(...),
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    service.get_by_id(subject_id)
    filename = await service.upload_subject_image(file)

    relative_path = f"/images/subjects/{filename}"

    service.update(subject_id, SubjectUpdateServiceDTO(image=relative_path))

    return ImageResponse(image_url=service._file_service.get_subject_image_url(relative_path))


@router.delete("/{subject_id}/image")
async def delete_subject_image(
    subject_id: int,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    subject = service.get_by_id(subject_id)
    if subject.image:
        service.delete_subject_image(subject.image)
        service.update(subject_id, SubjectUpdateServiceDTO(image=""))
    return {"message": "Image deleted successfully"}


@router.post(
    "/merge",
    summary="Объединить предметы",
    description="Объединение двух предметов",
    responses={
        **get_common_responses("create"),
        **get_error_responses(SubjectNotFoundService),
    },
)
async def merge_subjects(
    source_subject_id: int,
    target_subject_id: int,
    service: SubjectServiceInterface = Depends(get_subject_service),
):
    result = service.merge_subjects(source_subject_id, target_subject_id)
    return {
        "message": "Subjects merged successfully",
        "merged_subject": result,
        "source_subject_id": source_subject_id,
        "target_subject_id": target_subject_id,
    }
