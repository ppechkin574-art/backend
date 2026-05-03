import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from api.dependencies import allow_only_admins, get_import_service, get_question_service
from api.exceptions.documentation import get_common_responses, get_error_responses
from api.routes.quiz.converters import (
    to_question_create_service,
    to_question_list_response,
    to_question_update_service,
)
from api.routes.quiz.dtos import (
    QuestionCreateDTO,
    QuestionListQueryDTO,
    QuestionListResponseDTO,
    QuestionUpdateDTO,
)
from quiz.dtos.enums import BlockType, TestType
from quiz.dtos.questions import QuestionServiceDTO, QuestionsStatsDTO
from quiz.exceptions import (
    InvalidFormat,
    InvalidImportData,
    MissingColumns,
    QuestionNotFound,
    SubjectNotFound,
    TestTypeDontImport,
    TopicNotFound,
)
from quiz.services._import import ImportService
from quiz.services.questions import QuestionServiceInterface

router = APIRouter(
    prefix="/admin/questions",
    tags=["Admin - Questions"],
    dependencies=[Depends(allow_only_admins)],
)

logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=QuestionListResponseDTO,
    summary="Получить вопросы",
    description="Возвращает список вопросов с пагинацией, фильтрацией и сортировкой",
    responses={
        **get_common_responses("read"),
        **get_error_responses(QuestionNotFound, TopicNotFound, SubjectNotFound),
    },
)
async def get_questions(
    query: QuestionListQueryDTO = Depends(),
    service: QuestionServiceInterface = Depends(get_question_service),
):
    questions, total_count = service.list(
        page=query.page,
        page_size=query.page_size,
        search=query.search if query.search else None,
        sort_by=query.sort_columns[0] if query.sort_columns else None,
        sort_order=("asc" if (query.is_sort_ascendings and query.is_sort_ascendings[0]) else "desc"),
        difficulty=query.get_difficulty_list(),
        question_type=query.get_question_type_list(),
        subject_ids=query.get_subject_ids_list(),
        topic_ids=query.get_topic_ids_list(),
        usage_type=query.usage_type,
    )

    return to_question_list_response(questions, total_count)


@router.get(
    "/{question_id}",
    response_model=QuestionServiceDTO,
    summary="Получить вопрос по ID",
    description="Возвращает детальную информацию о вопросе",
    responses={
        **get_common_responses("read"),
        **get_error_responses(QuestionNotFound),
    },
)
async def get_question_by_id(
    question_id: int,
    service: QuestionServiceInterface = Depends(get_question_service),
):
    if question := service.get_by_id(question_id):
        return question
    else:
        raise HTTPException(status_code=404, detail="Question not found")


@router.post(
    "",
    response_model=QuestionServiceDTO,
    status_code=201,
    summary="Создать вопрос",
    description="Создание нового вопроса",
    responses={
        **get_common_responses("create"),
        **get_error_responses(TopicNotFound),
    },
)
async def create_question(
    question_create: QuestionCreateDTO,
    service: QuestionServiceInterface = Depends(get_question_service),
):
    return service.create(to_question_create_service(question_create))


@router.patch(
    "/{question_id}",
    response_model=QuestionServiceDTO,
    summary="Обновить вопрос",
    description="Частичное обновление вопроса",
    responses={
        **get_common_responses("update"),
        **get_error_responses(QuestionNotFound, TopicNotFound),
    },
)
async def update_question(
    question_id: int,
    question_update: QuestionUpdateDTO,
    service: QuestionServiceInterface = Depends(get_question_service),
):
    logger.info("Updating question %s", question_id)
    result = service.update(question_id, to_question_update_service(question_update))
    logger.info("Successfully updated question %s", question_id)
    return result


@router.delete(
    "/{question_id}",
    summary="Удалить вопрос",
    description="Удаление вопроса",
    responses={
        **get_common_responses("delete"),
        **get_error_responses(QuestionNotFound),
    },
)
async def delete_question(
    question_id: int,
    service: QuestionServiceInterface = Depends(get_question_service),
):
    service.delete(question_id)
    return {"message": "Question deleted successfully"}


@router.post(
    "/import",
    summary="Импорт вопросов",
    description="Импорт вопросов из Excel файла",
    responses={
        **get_common_responses("create"),
        **get_error_responses(InvalidFormat, InvalidImportData, MissingColumns, TestTypeDontImport),
    },
)
async def import_questions(
    file: UploadFile = File(...),
    import_type: TestType = Form(...),
    import_service: ImportService = Depends(get_import_service),
):
    result = await import_service.import_questions(file, import_type)
    return JSONResponse(status_code=201, content=result)


@router.post(
    "/import/preview",
    summary="Предпросмотр импорта вопросов",
    description="Возвращает распарсенные вопросы из Excel файла без сохранения в базу",
    responses={
        **get_common_responses("create"),
        **get_error_responses(InvalidFormat, InvalidImportData, MissingColumns, TestTypeDontImport),
    },
)
async def preview_import_questions(
    file: UploadFile = File(...),
    import_type: TestType = Form(...),
    import_service: ImportService = Depends(get_import_service),
):
    """Эндпоинт для предпросмотра импорта без сохранения в базу"""
    try:

        class ImportFormData:
            def __init__(self, file, type):
                self.file = file
                self.type = type

        form_data = ImportFormData(file=file, type=import_type)

        questions, ent_options, errors, errors_count = import_service.parser.parse(form_data)

        preview_questions = []

        for idx, question in enumerate(questions):
            question_text = ""
            for block in question.question_blocks:
                if hasattr(block, "value"):
                    if hasattr(block, "type") and block.type == BlockType.text:
                        question_text += block.value + " "
                    else:
                        question_text += block.value + " "

            question_text = question_text.strip()

            options = []
            for variant_idx, variant in enumerate(question.answers):
                variant_text = ""
                for block in variant.blocks:
                    if hasattr(block, "value"):
                        variant_text += block.value + " "

                variant_text = variant_text.strip()

                options.append(
                    {
                        "option_text": variant_text,
                        "is_correct": variant.is_correct,
                        "order_index": variant_idx,
                        "blocks": ([block.dict() for block in variant.blocks] if hasattr(variant, "blocks") else []),
                    }
                )

            explanation = ""
            if question.hint_blocks:
                hint_text = ""
                for block in question.hint_blocks:
                    if hasattr(block, "value"):
                        hint_text += block.value + " "
                explanation = hint_text.strip()

            preview_questions.append(
                {
                    "order_index": idx,
                    "question_text": question_text,
                    "question_type": question.type.value,
                    "options": options,
                    "explanation": explanation,
                    "difficulty": (question.difficulty.value if question.difficulty else "medium"),
                    "subject": question.subject,
                    "topic_name": question.topic_name,
                    "ent_option_number": question.ent_option_number,
                    "original_data": {
                        "question_blocks": (
                            [block.dict() for block in question.question_blocks]
                            if hasattr(question, "question_blocks")
                            else []
                        ),
                        "answer_blocks": (
                            [[block.dict() for block in variant.blocks] for variant in question.answers]
                            if hasattr(question, "answers")
                            else []
                        ),
                        "hint_blocks": (
                            [block.dict() for block in question.hint_blocks] if question.hint_blocks else []
                        ),
                    },
                }
            )

        question_types = {
            "single_choice": len([q for q in questions if q.type.value == "single_choice"]),
            "multiple_choice": len([q for q in questions if q.type.value == "multiple_choice"]),
            "ent": len([q for q in questions if q.type.value == "ent"]),
        }

        has_media = False
        has_latex = False
        total_options = sum(len(q.answers) for q in questions)

        for question in questions:
            for block in question.question_blocks:
                if hasattr(block, "value"):
                    if "{" in block.value and "http" in block.value and "}" in block.value:
                        has_media = True
                    if 'r"' in block.value or "r'" in block.value:
                        has_latex = True

            for variant in question.answers:
                for block in variant.blocks:
                    if hasattr(block, "value"):
                        if "{" in block.value and "http" in block.value and "}" in block.value:
                            has_media = True
                        if 'r"' in block.value or "r'" in block.value:
                            has_latex = True

            if question.hint_blocks:
                for block in question.hint_blocks:
                    if hasattr(block, "value"):
                        if "{" in block.value and "http" in block.value and "}" in block.value:
                            has_media = True
                        if 'r"' in block.value or "r'" in block.value:
                            has_latex = True

        return {
            "success": errors_count == 0,
            "questions": preview_questions,
            "errors": errors,
            "errors_count": errors_count,
            "questions_count": len(preview_questions),
            "file_name": file.filename,
            "analysis": {
                "has_media": has_media,
                "has_latex": has_latex,
                "question_types": question_types,
                "total_options": total_options,
            },
            "message": f"Найдено {len(preview_questions)} вопросов, ошибок: {errors_count}",
            "metadata": {
                "import_type": import_type.value,
                "subjects": list({q.subject for q in questions}),
                "topics": list({q.topic_name for q in questions if q.topic_name}),
                "ent_options": list({q.ent_option_number for q in questions if q.ent_option_number}),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in preview_import_questions: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@router.get(
    "/stats/overview",
    response_model=QuestionsStatsDTO,
    summary="Статистика вопросов",
    description="Возвращает общую статистику по вопросам",
    responses={
        **get_common_responses("read"),
    },
)
async def get_questions_stats(
    service: QuestionServiceInterface = Depends(get_question_service),
):
    questions_in_trainers = service.get_questions_in_trainers()
    questions_in_ent_options = service.get_questions_in_ent_options()
    subject_stats = service.get_question_stats_by_subject()
    topic_stats = service.get_question_stats_by_topic()

    _, total_questions = service.list(page=1, page_size=1)

    return QuestionsStatsDTO(
        total_questions=total_questions,
        questions_in_trainers=len(questions_in_trainers),
        questions_in_ent_options=len(questions_in_ent_options),
        questions_by_subject=[{"subject_id": k, "count": v} for k, v in subject_stats.items()],
        questions_by_topic=[{"topic_id": k, "count": v} for k, v in topic_stats.items()],
    )
