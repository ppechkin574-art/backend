"""Admin — «Скоро запускаем» screen copy. Edit the two-part title and the
subtitle (RU + KK) that used to be hardcoded l10n strings. Single settings row.

- GET   /admin/coming-soon/settings
- PATCH /admin/coming-soon/settings
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.dependencies import allow_read_or_admin_write, get_db_session
from coming_soon.settings import (
    ComingSoonSettingsDTO,
    ComingSoonSettingsUpdateDTO,
    get_or_create_coming_soon_settings,
    save_coming_soon_settings,
)

router = APIRouter(
    prefix="/admin/coming-soon",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get("/settings", response_model=ComingSoonSettingsDTO)
def get_coming_soon_settings(session: Session = Depends(get_db_session)):
    row = get_or_create_coming_soon_settings(session)
    session.commit()
    return ComingSoonSettingsDTO.model_validate(row)


@router.patch("/settings", response_model=ComingSoonSettingsDTO)
def update_coming_soon_settings(
    body: ComingSoonSettingsUpdateDTO,
    session: Session = Depends(get_db_session),
):
    row = save_coming_soon_settings(session, body.model_dump(exclude_unset=True))
    session.commit()
    return ComingSoonSettingsDTO.model_validate(row)
