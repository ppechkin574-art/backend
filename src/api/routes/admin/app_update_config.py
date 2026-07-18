"""Admin endpoints for the mobile force-update config.

Single singleton row (per-platform `min_build` + `store_url`). The public
`GET /app/update-config` reads it; here the admin edits it WITHOUT a
backend redeploy.

Endpoints (gated by `allow_read_or_admin_write`):
- GET /admin/app-update-config — current values
- PUT /admin/app-update-config — partial update (all fields optional)

The route owns the commit (mirrors leaderboard-prizes): the service
flushes, the route commits after a successful save.
"""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.dependencies import (
    allow_read_or_admin_write,
    get_app_update_config_service,
    get_cache_service,
)
from auth.dtos import UserDTO
from quiz.dtos.app_update_config import (
    AppUpdateConfigAuditDTO,
    AppUpdateConfigDTO,
    AppUpdateConfigUpdateDTO,
)
from quiz.services.app_update_config import (
    PUBLIC_CACHE_KEY,
    AppUpdateConfigService,
)
from utils.cache import CacheService

# Hosts a store URL is allowed to point at, per platform. Guards against an
# operator pasting a phishing / competitor / typo link into the "Обновить"
# button that every gated user taps.
_ALLOWED_STORE_HOSTS = {
    "ios": {"apps.apple.com", "itunes.apple.com"},
    "android": {"play.google.com"},
}


def _validate_builds(body: AppUpdateConfigUpdateDTO, current) -> None:
    """Reject incoherent build thresholds before they reach production.

    PUT is partial, so the effective value of each field is the incoming
    value when set, otherwise the current persisted one. Per platform:
    - `min_build` (hard force) may not exceed `last_known_build` (when set
      > 0) — otherwise users below it are bricked onto a version that is
      not downloadable (and Apple review dead-ends → 2.1 reject).
    - `recommended_build` (soft prompt) must sit between `min_build` and
      `last_known_build`: a soft target below the forced floor is a no-op,
      and one above what is published would prompt toward a missing build.
    A `last_known_build` of 0 means "unknown": no hard ceiling (the panel
    warns instead), preserving the old behaviour for un-configured rows.
    """

    def eff(field: str) -> int:
        v = getattr(body, field)
        return v if v is not None else getattr(current, field)

    errors: list[str] = []
    for platform, min_f, lk_f, rec_f in (
        (
            "iOS",
            "ios_min_build",
            "ios_last_known_build",
            "ios_recommended_build",
        ),
        (
            "Android",
            "android_min_build",
            "android_last_known_build",
            "android_recommended_build",
        ),
    ):
        min_build = eff(min_f)
        last_known = eff(lk_f)
        recommended = eff(rec_f)

        if last_known > 0 and min_build > last_known:
            errors.append(
                f"{platform}: min_build={min_build} превышает последний "
                f"опубликованный в сторе build={last_known}. Это заблокирует "
                f"пользователей на версию, которой ещё нет в сторе. Сначала "
                f"дождитесь публикации билда и обновите «последний build в сторе»."
            )
        if recommended > 0:
            if recommended < min_build:
                errors.append(
                    f"{platform}: recommended_build={recommended} меньше "
                    f"min_build={min_build} — мягкое окно не имеет смысла "
                    f"(все ниже min уже форсятся жёстко)."
                )
            if last_known > 0 and recommended > last_known:
                errors.append(
                    f"{platform}: recommended_build={recommended} превышает "
                    f"последний опубликованный build={last_known} — нельзя "
                    f"рекомендовать версию, которой ещё нет в сторе."
                )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=" ".join(errors),
        )

def _validate_store_urls(body: AppUpdateConfigUpdateDTO, current) -> None:
    """Reject store URLs that don't point at the real store for the platform.

    Only validates URLs being SET in this request (the partial patch) and
    only when non-empty — an empty string clears the URL and is allowed.
    Requires https + an allow-listed host so the "Обновить" button can never
    deep-link users to an arbitrary / malicious page.
    """
    errors: list[str] = []
    for platform, field in (
        ("ios", "ios_store_url"),
        ("android", "android_store_url"),
    ):
        url = getattr(body, field)
        if url is None:
            continue  # not being changed
        url = url.strip()
        if not url:
            continue  # clearing the URL is fine
        # Reject internal whitespace / control chars: .strip() only trims the
        # ends, so a pasted "…id6766537009 AIMA EHT" would slip through the
        # host check (host is still apps.apple.com) yet break launchUrl on the
        # client — leaving a forced user on a dead "Обновить" button.
        if any(ch.isspace() or ord(ch) < 0x20 for ch in url):
            errors.append(
                f"{platform}: ссылка не должна содержать пробелов или "
                f"переносов строк. Получено: {url!r}."
            )
            continue
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in _ALLOWED_STORE_HOSTS[platform]:
            allowed = " / ".join(sorted(_ALLOWED_STORE_HOSTS[platform]))
            errors.append(
                f"{platform}: ссылка должна быть https и вести на {allowed}. "
                f"Получено: {url!r}."
            )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=" ".join(errors),
        )


router = APIRouter(
    prefix="/admin/app-update-config",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get(
    "",
    response_model=AppUpdateConfigDTO,
    summary="Текущий конфиг force-update",
)
def get_config(
    service: AppUpdateConfigService = Depends(get_app_update_config_service),
):
    return AppUpdateConfigDTO.model_validate(service.get())


@router.put(
    "",
    response_model=AppUpdateConfigDTO,
    summary="Изменить конфиг force-update",
)
def update_config(
    body: AppUpdateConfigUpdateDTO,
    admin: UserDTO = Depends(allow_read_or_admin_write),
    service: AppUpdateConfigService = Depends(get_app_update_config_service),
    cache: CacheService = Depends(get_cache_service),
):
    # Guard against incoherent thresholds (forcing/recommending a build
    # that is not yet published) and bad store URLs. Uses current row + the
    # partial patch.
    current = service.get()
    _validate_builds(body, current)
    _validate_store_urls(body, current)
    config = service.update(body, updated_by=admin.email or str(admin.id))
    service.repo.db.commit()
    # Drop the cached public payload so the mobile app sees the change on the
    # next request (best-effort; the TTL is the backstop if Redis is down).
    cache.delete(PUBLIC_CACHE_KEY)
    return AppUpdateConfigDTO.model_validate(config)


@router.get(
    "/history",
    response_model=list[AppUpdateConfigAuditDTO],
    summary="История изменений force-update (для отката)",
)
def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    service: AppUpdateConfigService = Depends(get_app_update_config_service),
):
    return [
        AppUpdateConfigAuditDTO.model_validate(row)
        for row in service.history(limit)
    ]
