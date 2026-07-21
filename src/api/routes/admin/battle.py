"""Admin — battle tuning (CRM). Edit the values that used to be hardcoded:
stars per outcome (win/draw/loss), format (questions per subject, time) and
bot difficulty. Single settings row.

- GET   /admin/battle/settings
- PATCH /admin/battle/settings
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.dependencies import allow_read_or_admin_write, get_db_session
from battle.settings import (
    BattleSettingsDTO,
    BattleSettingsUpdateDTO,
    get_or_create_battle_settings,
    save_battle_settings,
)

router = APIRouter(
    prefix="/admin/battle",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get("/settings", response_model=BattleSettingsDTO)
def get_battle_settings(session: Session = Depends(get_db_session)):
    row = get_or_create_battle_settings(session)
    session.commit()
    return BattleSettingsDTO.model_validate(row)


@router.patch("/settings", response_model=BattleSettingsDTO)
def update_battle_settings(
    body: BattleSettingsUpdateDTO,
    session: Session = Depends(get_db_session),
):
    row = save_battle_settings(session, body.model_dump(exclude_unset=True))
    session.commit()
    return BattleSettingsDTO.model_validate(row)
