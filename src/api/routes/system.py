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


@router.get("/system/kk-pilot-status")
async def kk_pilot_status(request: Request):
    """Phase 7b pilot diagnostic — does NOT require auth because it
    only exposes aggregate counts and a non-PII sample question id.

    Returns the alembic head the worker booted with + how many
    questions currently have `question_text_kk` populated + a single
    sample id for spot-checking via psql.  Used to verify the data
    migration applied without needing shell access to Railway.
    """
    from sqlalchemy import text

    try:
        container = request.app.state.container
        db = container.database()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"db DI unavailable: {exc!r}"}

    session = db.session
    try:
        alembic_rev = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        kk_count = session.execute(
            text(
                "SELECT COUNT(*) FROM questions WHERE question_text_kk IS NOT NULL"
            )
        ).scalar()
        sample = session.execute(
            text(
                "SELECT id, LEFT(question_text_kk, 80) "
                "FROM questions WHERE question_text_kk IS NOT NULL "
                "ORDER BY id LIMIT 1"
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"query failed: {exc!r}"}
    finally:
        session.close()

    return {
        "ok": True,
        "alembic_head": alembic_rev,
        "questions_with_kk_text": kk_count,
        "sample": (
            {"id": sample[0], "text_preview": sample[1]} if sample else None
        ),
    }


routers = [router]
