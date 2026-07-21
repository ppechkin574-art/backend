"""Public read-only endpoint for the «Скоро запускаем» screen copy.

The app fetches this when the coming-soon screen opens (tapped a not-yet-
launched banner), falling back to its bundled l10n strings if the request
fails. Both languages are returned — the app picks by interface locale, same
as it does for /events. `subtitle_*` is a template: the app replaces the
literal ``{title}`` with the tapped event's name.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from coming_soon.settings import ComingSoonSettingsDTO, get_or_create_coming_soon_settings

router = APIRouter(prefix="/coming-soon", tags=["user"])


@router.get("", response_model=ComingSoonSettingsDTO)
def get_coming_soon(session: Session = Depends(get_db_session)):
    row = get_or_create_coming_soon_settings(session)
    session.commit()
    return ComingSoonSettingsDTO.model_validate(row)
