from fastapi import APIRouter, Depends

from api.dependencies import (
    get_progress_service,
    get_student,
    get_user,
    require_active_subscription,
)
from quiz.dtos.progress import (
    EntOptionsProgressSummaryDTO,
    TrainersProgressSummaryDTO,
    UserProgressOverviewDTO,
)
from quiz.services.progress import ProgressService
from utils.monitoring import log_info

router = APIRouter(
    prefix="/user/progress",
    tags=["User - Progress"],
    dependencies=[Depends(get_user), Depends(require_active_subscription())],
)


@router.get(
    "/trainers/summary",
    response_model=TrainersProgressSummaryDTO,
    summary="Сводка прогресса по тренажёрам",
    description="Возвращает общий прогресс пользователя по всем тренажёрам",
)
async def get_trainers_progress_summary(
    student=Depends(get_student),
    progress_service: ProgressService = Depends(get_progress_service),
):
    log_info(
        "Trainers progress summary request",
        user_id=student.id,
        action="get_trainers_progress_summary",
        resource="progress",
    )

    summary = progress_service.get_trainers_progress_summary(student.id)

    log_info(
        "Trainers progress summary retrieved",
        user_id=student.id,
        total_trainers=summary.total_trainers,
        overall_progress=summary.overall_progress,
    )

    return summary


@router.get(
    "/ents/summary",
    response_model=EntOptionsProgressSummaryDTO,
    summary="Сводка прогресса по пробным ЕНТ",
    description="Возвращает общий прогресс пользователя по всем вариантам ЕНТ",
)
async def get_ent_options_progress_summary(
    student=Depends(get_student),
    progress_service: ProgressService = Depends(get_progress_service),
):
    log_info(
        "ENT options progress summary request",
        user_id=student.id,
        action="get_ent_options_progress_summary",
        resource="progress",
    )

    summary = progress_service.get_ent_options_progress_summary(student.id)

    log_info(
        "ENT options progress summary retrieved",
        user_id=student.id,
        total_options=summary.total_options,
        overall_progress=summary.overall_progress,
    )

    return summary


# @router.get(
#     "/trainers/detailed",
#     response_model=list[TrainerProgressDetailDTO],
#     summary="Детальный прогресс по тренажёрам",
#     description="Возвращает детальный прогресс по каждому тренажёру",
# )
# async def get_detailed_trainers_progress(
#     student=Depends(get_student),
#     progress_service: ProgressService = Depends(get_progress_service),
# ):
#     log_info(
#         "Detailed trainers progress request",
#         user_id=student.id,
#         action="get_detailed_trainers_progress",
#         resource="progress",
#     )

#     detailed = progress_service.get_detailed_trainers_progress(student.id)

#     log_info(
#         "Detailed trainers progress retrieved",
#         user_id=student.id,
#         trainers_count=len(detailed),
#     )

#     return detailed


# @router.get(
#     "/ents/detailed",
#     response_model=list[EntOptionProgressDetailDTO],
#     summary="Детальный прогресс по пробным ЕНТ",
#     description="Возвращает детальный прогресс по каждому варианту ЕНТ",
# )
# async def get_detailed_ent_options_progress(
#     student=Depends(get_student),
#     progress_service: ProgressService = Depends(get_progress_service),
# ):
#     log_info(
#         "Detailed ENT options progress request",
#         user_id=student.id,
#         action="get_detailed_ent_options_progress",
#         resource="progress",
#     )

#     detailed = progress_service.get_detailed_ent_options_progress(student.id)

#     log_info(
#         "Detailed ENT options progress retrieved",
#         user_id=student.id,
#         options_count=len(detailed),
#     )

#     return detailed


@router.get(
    "/overview",
    response_model=UserProgressOverviewDTO,
    summary="Общий обзор прогресса",
    description="Возвращает общий обзор прогресса пользователя по всем направлениям",
)
async def get_user_progress_overview(
    student=Depends(get_student),
    progress_service: ProgressService = Depends(get_progress_service),
):
    log_info(
        "User progress overview request",
        user_id=student.id,
        action="get_user_progress_overview",
        resource="progress",
    )

    overview = progress_service.get_user_progress_overview(student.id)

    log_info(
        "User progress overview retrieved",
        user_id=student.id,
        overall_progress=overview.overall_progress,
        streak_days=overview.streak_days,
    )

    return overview
