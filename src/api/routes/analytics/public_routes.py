import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.exceptions import HTTPException
from fastapi.responses import Response

from analytics.dtos.events import EventCreateServiceDTO
from analytics.exceptions import WrongEventMetaData
from analytics.service import AnalyticServiceInterface
from api.dependencies import get_analytics_service, get_current_user_id_optional

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/analytics",
    tags=["System - Analytics"],
    # dependencies=[Depends(allow_only_admins)],
)


@router.post("/events")
def save_event(
    event: EventCreateServiceDTO,
    user_id: UUID | None = Depends(get_current_user_id_optional),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
    authorization: str | None = Header(None, description="Authorization token (Bearer)"),
):
    logger.info(
        "Received event: session_id=%s, has_auth_header=%s, user_id_from_token=%s",
        event.session_id,
        authorization is not None,
        user_id,
    )

    if user_id:
        logger.info("Setting user_id from token: %s", user_id)
        event.user_id = user_id
    else:
        logger.info("No valid token provided, keeping user_id from request or None")

    try:
        service.save_event(event)
    except WrongEventMetaData as meta_ex:
        raise HTTPException(400, f"Not valid metadata: {meta_ex}")
    except Exception as ex:
        logger.exception("Error saving event: %s", ex)
        raise HTTPException(400, f"Error: {ex}")
    return Response(status_code=200)
