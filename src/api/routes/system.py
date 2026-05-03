from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(tags=["System"])


@router.get("/")
async def root():
    return {
        "version": "0.1.3",
        "status": "running",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


routers = [router]
