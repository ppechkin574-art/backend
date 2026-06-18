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

import contextlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from api.dependencies import allow_only_admins

router = APIRouter(tags=["System"])


@router.get("/")
async def root():
    return {
        "status": "running",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health")
async def health(request: Request):
    redis_ok = _ping_redis(request)
    return {
        "status": "healthy" if redis_ok else "degraded",
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


@router.get("/system/kk-pilot-status", dependencies=[Depends(allow_only_admins)], include_in_schema=False)
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
        # Per-subject coverage — helps decide whether the pilot needs
        # more translations sourced externally or whether the import
        # missed rows that ARE available in the source JSON.
        coverage_rows = session.execute(
            text(
                """
                SELECT
                    s.name AS subject,
                    COUNT(q.id) AS total,
                    COUNT(q.question_text_kk) AS with_kk
                FROM subjects s
                LEFT JOIN questions q ON q.subject_id = s.id
                GROUP BY s.name
                ORDER BY s.name
                """
            )
        ).fetchall()
        # IDs of Math questions still lacking kk — capped to 20 so the
        # response stays small.  Useful for cross-checking against the
        # source JSON.
        missing_math_ids = session.execute(
            text(
                """
                SELECT q.id
                FROM questions q
                JOIN subjects s ON s.id = q.subject_id
                WHERE s.name = 'Математика'
                  AND q.question_text_kk IS NULL
                ORDER BY q.id
                LIMIT 20
                """
            )
        ).fetchall()
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
        "coverage_by_subject": [
            {"subject": row[0], "total": row[1], "with_kk": row[2]}
            for row in coverage_rows
        ],
        "math_missing_kk_ids_sample": [row[0] for row in missing_math_ids],
    }


def _empty_update_config() -> dict:
    """Fail-soft default — min_build=0 means the app never force-updates."""
    return {
        "ios": {"min_build": 0, "recommended_build": 0, "store_url": ""},
        "android": {"min_build": 0, "recommended_build": 0, "store_url": ""},
    }


@router.get("/app/update-config")
async def app_update_config(request: Request):
    """Force-update config for the mobile app (public, no auth).

    Reads the singleton `app_update_config` DB row, editable by admins via
    the admin panel — NO deploy needed to force an update on release.
    Default min_build=0 → the app never force-updates (its build is always
    >= 0). The app compares its own build number against `min_build` for its
    platform and shows a blocking update modal when its build is lower.

    FAIL-SOFT: any DB / DI error returns zeros/empty (min_build=0) so a
    transient DB hiccup can never force-update — or 500 — the whole app.
    """
    from quiz.services.app_update_config import (
        PUBLIC_CACHE_KEY,
        PUBLIC_CACHE_TTL,
    )

    try:
        container = request.app.state.container
    except Exception:  # noqa: BLE001 — fail-soft, never 500
        return _empty_update_config()

    # Read-through Redis cache. Fail-soft: any cache error just falls through
    # to the DB read, so a Redis hiccup can never break the gate.
    cache = None
    try:
        cache = container.cache_service()
        cached = cache.get(PUBLIC_CACHE_KEY)
        if cached:
            return cached
    except Exception:  # noqa: BLE001
        cache = None

    try:
        db = container.database()
    except Exception:  # noqa: BLE001 — fail-soft, never 500
        return _empty_update_config()

    session = db.session
    try:
        from quiz.repositories.app_update_config import (
            AppUpdateConfigRepository,
        )

        config = AppUpdateConfigRepository(session).get_or_create()
        # Read attributes before closing the session.
        result = {
            "ios": {
                "min_build": config.ios_min_build or 0,
                "recommended_build": config.ios_recommended_build or 0,
                "store_url": config.ios_store_url or "",
            },
            "android": {
                "min_build": config.android_min_build or 0,
                "recommended_build": config.android_recommended_build or 0,
                "store_url": config.android_store_url or "",
            },
        }
        # get_or_create may have inserted the seed row on first boot.
        session.commit()
        if cache is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001
                cache.set(PUBLIC_CACHE_KEY, result, ttl=PUBLIC_CACHE_TTL)
        return result
    except Exception:  # noqa: BLE001 — fail-soft, never 500
        with contextlib.suppress(Exception):  # noqa: BLE001
            session.rollback()
        return _empty_update_config()
    finally:
        session.close()


routers = [router]
