"""System endpoints: root + health-check.

`/health` is the endpoint Railway is configured to ping; it must stay
fast and fail-soft. We don't want Railway to restart the service every
time Redis hiccups for 200ms — restarts don't fix transient backend-
service problems and only cause more downtime.

The contract:
  * `status` is always returned ("healthy" / "degraded").
  * Sub-service results (`redis`) are reported but never gate the
    response code. The response is always 200 if the Python process can
    reply at all — that's enough to prove the worker is alive.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

router = APIRouter(tags=["System"])


@router.get("/")
async def root():
    return {
        "version": "0.1.3",
        "status": "running",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health")
async def health(request: Request):
    redis_ok = _ping_redis(request)
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "up" if redis_ok else "down",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _ping_redis(request: Request) -> bool:
    """Ping Redis via the DI container if available. Never raises — a
    healthcheck must never throw, otherwise Railway flaps the service."""
    try:
        container = request.app.state.container
        redis = container.redis()
        return bool(redis.ping())
    except Exception:
        return False


routers = [router]
