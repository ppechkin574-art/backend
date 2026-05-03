from fastapi import APIRouter, Depends, HTTPException

from api.common import ListDTO, ListQueryDTO
from api.dependencies import allow_only_admins, get_ent_options_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.dtos import (
    DeleteResponseDTO,
    EntOptionCreateRequestDTO,
    EntOptionUpdateRequestDTO,
)
from quiz.dtos.ent_options import (
    EntOptionsServiceDTO,
    EntOptionWithQuestionsDTO,
    EntQuestionCheckDTO,
    EntQuestionOperationDTO,
    EntQuestionsCountDTO,
)
from quiz.exceptions import (
    EntOptionAlreadyExist,
    EntOptionsDoesntExist,
    SubjectNotFound,
)
from quiz.services.ent_options import EntOptionServiceInterface

router = APIRouter(
    prefix="/admin/ents",
    tags=["Admin - ENTs"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get(
    "",
    response_model=ListDTO[EntOptionsServiceDTO],
    summary="Получить ЕНТ варианты",
    description="Возвращает список ЕНТ вариантов с пагинацией",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_all_ent_options(
    query: ListQueryDTO = Depends(),
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    options, total_count = service.get_all_ent_options(page=query.page, page_size=query.page_size, search=query.search)

    return ListDTO[EntOptionsServiceDTO](
        draw=query.draw,
        records_total=total_count,
        records_filtered=total_count,
        data=options,
    )


@router.get(
    "/max_option_number",
    response_model=int,
    summary="Получить максимальный номер варианта ЕНТ",
    description="Возвращает максимальный номер варианта ЕНТ",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_max_ent_option(
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    return service.get_max_option_number()


@router.get(
    "/{ent_option_id}",
    response_model=EntOptionWithQuestionsDTO,
    summary="Получить ЕНТ вариант с вопросами",
    description="Возвращает детальную информацию о ЕНТ варианте",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_ent_option_details(
    ent_option_id: int,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    return service.get_ent_with_questions(ent_option_id)


@router.get(
    "/{ent_option_id}/questions",
    summary="Получить вопросы ЕНТ варианта",
    description="Возвращает все вопросы ЕНТ варианта",
    responses={
        **get_common_responses("read"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def get_ent_questions(
    ent_option_id: int,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    return service.get_ent_questions(ent_option_id)


@router.post(
    "/create",
    response_model=EntOptionsServiceDTO,
    status_code=201,
    summary="Создать ЕНТ вариант",
    description="Создание нового ЕНТ варианта",
    responses={
        **get_common_responses("create"),
        **get_error_responses(SubjectNotFound, EntOptionAlreadyExist),
    },
)
async def create_ent_option(
    ent_data: EntOptionCreateRequestDTO,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    return service.create(ent_data)


@router.patch(
    "/{ent_option_id}",
    response_model=EntOptionsServiceDTO,
    summary="Обновить ЕНТ вариант",
    description="Обновление существующего ЕНТ варианта",
    responses={
        **get_common_responses("update"),
        **get_error_responses(EntOptionsDoesntExist, SubjectNotFound, EntOptionAlreadyExist),
    },
)
async def update_ent_option(
    ent_option_id: int,
    ent_data: EntOptionUpdateRequestDTO,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    return service.update(ent_option_id, ent_data)


@router.delete(
    "/{ent_option_id}",
    response_model=DeleteResponseDTO,
    summary="Удалить ЕНТ вариант",
    description="Удаление ЕНТ варианта",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(EntOptionsDoesntExist),
    },
)
async def delete_ent_option(
    ent_option_id: int,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    service.delete(ent_option_id)
    return DeleteResponseDTO(message="ENT option deleted successfully")


@router.post(
    "/{ent_option_id}/questions/add",
    summary="Добавить вопросы в вариант ЕНТ",
    description="Добавляет несколько вопросов в вариант ЕНТ",
    responses={
        200: {"description": "Вопросы успешно добавлены"},
        404: {"description": "Вариант ЕНТ или вопросы не найдены"},
    },
)
async def add_questions_to_ent_option(
    ent_option_id: int,
    question_data: EntQuestionOperationDTO,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    try:
        service.add_questions_to_option(ent_option_id, question_data.question_ids)
        return {"message": "Questions added successfully"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{ent_option_id}/questions/remove",
    summary="Удалить вопросы из варианта ЕНТ",
    description="Удаляет несколько вопросов из варианта ЕНТ",
    responses={
        200: {"description": "Вопросы успешно удалены"},
        404: {"description": "Вариант ЕНТ не найден"},
    },
)
async def remove_questions_from_ent_option(
    ent_option_id: int,
    question_data: EntQuestionOperationDTO,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    try:
        service.remove_questions_from_option(ent_option_id, question_data.question_ids)
        return {"message": "Questions removed successfully"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{ent_option_id}/questions/count",
    response_model=EntQuestionsCountDTO,
    summary="Получить количество вопросов в варианте ЕНТ",
    description="Возвращает количество вопросов в указанном варианте ЕНТ",
)
async def get_ent_questions_count(
    ent_option_id: int,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    try:
        return EntQuestionsCountDTO(
            ent_option_id=ent_option_id,
            question_count=service.get_ent_questions_count(ent_option_id),
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{ent_option_id}/questions/check/{question_id}",
    response_model=EntQuestionCheckDTO,
    summary="Проверить наличие вопроса в варианте ЕНТ",
    description="Проверяет, содержится ли вопрос в указанном варианте ЕНТ",
)
async def check_question_in_ent_option(
    ent_option_id: int,
    question_id: int,
    service: EntOptionServiceInterface = Depends(get_ent_options_service),
):
    try:
        return EntQuestionCheckDTO(
            ent_option_id=ent_option_id,
            question_id=question_id,
            exists=service.check_question_in_ent_option(ent_option_id, question_id),
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
