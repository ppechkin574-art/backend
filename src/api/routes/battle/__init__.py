from fastapi import APIRouter

from .rest_routes import router as rest_router
from .ws_routes import router as ws_router

battle_router = APIRouter()
battle_router.include_router(rest_router)
battle_router.include_router(ws_router)
