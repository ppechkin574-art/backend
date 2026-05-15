"""Two-layer SMS abuse defence, sitting on top of the existing slowapi
per-minute / per-hour limits.

LAYER 1 — global daily cap (`sms_daily_cap` in app_settings)
    Single counter for the whole service. When today's INCR exceeds
    the cap, /auth/code/request returns 503 for everyone (except the
    reviewer bypass contact) and fires a one-shot alert email to ops
    with the top-5 IPs by request volume. Protects the SMSC budget
    from being drained overnight by an attack that rotates IPs faster
    than slowapi can react.

LAYER 2 — per-IP daily block (`sms_ip_daily_block` in app_settings)
    Counter per source IP. Legitimate users typically make 1-3 OTP
    requests per day; an IP that crosses the threshold gets 429 for
    the rest of the day. Counter is reset by Redis TTL at midnight + 1h.

Both layers explicitly SKIP the reviewer bypass contact
(REVIEWER_TEST_PHONE, default +77001234567) — Apple App Review must
never be blocked by abuse defences, otherwise resubmission stalls.

Counters are increased AFTER the route handler returns (in the route),
not from inside AuthService — the service stays free of HTTP/Redis
plumbing and the abuse counters live next to the slowapi limits where
ops will look for them.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import HTTPException, status
from redis import Redis, RedisError
from starlette.requests import Request

from api.middlewares.rate_limit import _real_client_ip
from app_config.service import AppSettingsService
from clients.notification.client import NotificationClientEmail

logger = logging.getLogger(__name__)


# Counters expire at midnight UTC + 1h buffer. 25h covers timezone
# wobble around the daily-reset boundary so we never have a window
# where new counters are mixed with stale ones.
_COUNTER_TTL_SECONDS = 25 * 3600


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _is_reviewer_test_contact(contact: str) -> bool:
    """Same check the AuthService uses internally (see
    `auth/services.py::_is_reviewer_test_contact`). Duplicated here so
    we don't import the service into the middleware — would create a
    cycle and pull half the auth graph into this module."""
    test_phone = os.getenv("REVIEWER_TEST_PHONE")
    return bool(test_phone) and contact == test_phone


def _global_counter_key(day: str) -> str:
    return f"sms:daily:total:{day}"


def _ip_zset_key(day: str) -> str:
    """Sorted set of per-IP counts for the day. Member=IP, score=count.
    Sorted set lets us pull top-N IPs in O(log N) for the alert email
    without scanning a per-key namespace."""
    return f"sms:daily:ips:{day}"


def _alert_dedup_key(day: str) -> str:
    return f"alert:sms_cap:{day}"


def check_sms_quota(
    request: Request,
    contact: str,
    redis: Redis,
    app_settings: AppSettingsService,
) -> None:
    """Raise HTTPException if either quota is busted.

    Reads counters and thresholds from Redis / app_settings. The
    thresholds come from the editable `app_settings` table — operator
    can adjust them from the admin panel without a redeploy.

    Reviewer-bypass contacts are a no-op: Apple App Review must work
    even if the rest of the world has hit the daily cap.

    Order matters: per-IP check first (cheaper), global cap second
    (slightly heavier read, fires alert when crossed).
    """
    if _is_reviewer_test_contact(contact):
        return

    day = _today_utc()
    ip = _real_client_ip(request)

    # ─── per-IP daily block ───
    ip_block_threshold = app_settings.get_int("sms_ip_daily_block", 20)
    try:
        score = redis.zscore(_ip_zset_key(day), ip)
        ip_count = int(score) if score else 0
    except RedisError as e:
        logger.warning("[sms_quota] redis zscore failed: %s — fail-open", e)
        ip_count = 0

    if ip_count >= ip_block_threshold:
        logger.warning(
            "[sms_quota] IP %s blocked (count=%d threshold=%d)",
            ip,
            ip_count,
            ip_block_threshold,
        )
        # U2=(a): neutral message, no detail about threshold/time.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов. Попробуйте завтра.",
        )

    # ─── global daily cap ───
    daily_cap = app_settings.get_int("sms_daily_cap", 1000)
    try:
        total_raw = redis.get(_global_counter_key(day))
        global_count = int(total_raw) if total_raw else 0
    except RedisError as e:
        logger.warning("[sms_quota] redis get failed: %s — fail-open", e)
        global_count = 0

    if global_count >= daily_cap:
        logger.error(
            "[sms_quota] DAILY CAP HIT (count=%d cap=%d) — blocking all non-reviewer requests until tomorrow",
            global_count,
            daily_cap,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис временно недоступен. Попробуйте позже.",
        )


def record_sms_request(
    request: Request,
    contact: str,
    redis: Redis,
    app_settings: AppSettingsService,
    email_client: NotificationClientEmail | None = None,
) -> None:
    """INCR both counters. Reviewer bypass is excluded so Apple's traffic
    doesn't show up in metrics or push us toward the cap.

    Called from the route handler AFTER the service call returns —
    success or failure. Failed-send attempts still count toward the
    per-IP block (an attacker rotating bad numbers doesn't get to
    evade the block by causing SMSC errors) but rarely affect the
    global cap because real attacks tend to succeed at SMSC level
    too (SMSC charges for accepted-then-failed-delivery on some routes
    — see Annex 1 п. 6 of the contract).

    Crossing the cap on this very call → fires a one-shot alert email
    with top-5 IPs. Dedup'd by a daily Redis key so we don't spam ops
    even if the cap stays exceeded for hours.
    """
    if _is_reviewer_test_contact(contact):
        return

    day = _today_utc()
    ip = _real_client_ip(request)

    try:
        # Per-IP counter via sorted set: ZINCRBY also creates the member
        # on first hit, no separate check needed.
        new_ip_count = redis.zincrby(_ip_zset_key(day), 1, ip)
        redis.expire(_ip_zset_key(day), _COUNTER_TTL_SECONDS)

        new_total = redis.incr(_global_counter_key(day))
        redis.expire(_global_counter_key(day), _COUNTER_TTL_SECONDS)
    except RedisError as e:
        logger.warning("[sms_quota] counter increment failed: %s", e)
        return

    logger.debug(
        "[sms_quota] +1 ip=%s ip_count=%s total=%s",
        ip,
        int(new_ip_count) if new_ip_count else "?",
        new_total,
    )

    # If THIS call pushed us across the cap → fire the alert (once/day).
    daily_cap = app_settings.get_int("sms_daily_cap", 1000)
    if new_total >= daily_cap and email_client is not None:
        _fire_cap_alert_once(redis, email_client, day, int(new_total), daily_cap)


def _fire_cap_alert_once(
    redis: Redis,
    email_client: NotificationClientEmail,
    day: str,
    current_count: int,
    cap: int,
) -> None:
    """SET NX with TTL acts as a daily dedup latch — only the first
    crossing of the cap sends an email, subsequent calls find the key
    and exit. Without this we'd email ops on every request after the
    cap is hit, which is exactly the moment we want their inbox calm
    and readable.
    """
    try:
        first_alert = redis.set(_alert_dedup_key(day), "1", ex=_COUNTER_TTL_SECONDS, nx=True)
    except RedisError as e:
        logger.warning("[sms_quota] alert dedup check failed: %s", e)
        first_alert = False

    if not first_alert:
        return

    # U3=(b): include top-5 IPs by request count so ops can see if it's
    # one concentrated attacker (block at WAF/Cloudflare) or a wide
    # distributed surge (raise the cap or shift strategy).
    try:
        top = redis.zrevrange(_ip_zset_key(day), 0, 4, withscores=True)
    except RedisError as e:
        logger.warning("[sms_quota] top-IP fetch failed: %s", e)
        top = []

    rows_html = "".join(
        f"<tr><td><code>{ip.decode() if isinstance(ip, bytes) else ip}</code></td>"
        f"<td style='text-align:right'>{int(score)}</td></tr>"
        for ip, score in top
    )
    rows_text = "\n".join(
        f"  {ip.decode() if isinstance(ip, bytes) else ip}  →  {int(score)}"
        for ip, score in top
    )

    html = f"""<html><body style="font-family:system-ui,Arial,sans-serif;font-size:14px">
<h2>⚠️ AIMA — SMS daily cap exceeded</h2>
<p>Today's count crossed the configured cap. <b>/auth/code/request returns 503</b>
to all non-reviewer requests until midnight UTC.</p>

<table style="border-collapse:collapse;margin:8px 0">
<tr><td>Date (UTC):</td><td><b>{day}</b></td></tr>
<tr><td>Current count:</td><td><b>{current_count}</b></td></tr>
<tr><td>Configured cap:</td><td><b>{cap}</b></td></tr>
</table>

<h3>Top-5 IPs by request volume today</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse">
<tr><th>IP</th><th>Requests</th></tr>
{rows_html or "<tr><td colspan='2'><i>no IPs tracked</i></td></tr>"}
</table>

<p><b>What to do</b>:</p>
<ol>
<li>If one IP dominates → check Cloudflare/WAF, block that IP.</li>
<li>If distributed → consider raising <code>sms_daily_cap</code> in admin panel,
or activating stricter <code>sms_ip_daily_block</code>.</li>
<li>Monitor Railway logs for the IP — confirm patterns before unblocking.</li>
</ol>

<p style="color:#888;font-size:12px">— AIMA backend abuse-monitor</p>
</body></html>"""

    text = f"""AIMA — SMS daily cap exceeded.

Date (UTC): {day}
Current count: {current_count}
Configured cap: {cap}

Top-5 IPs today:
{rows_text or '  (no IPs tracked)'}

/auth/code/request returns 503 to all non-reviewer requests until midnight UTC.
Raise the cap via admin panel if the surge is legitimate.
"""

    alert_to = os.getenv("ALERT_EMAIL", "ppechkin574@gmail.com")
    try:
        email_client.send_alert(
            to=alert_to,
            subject=f"[AIMA] SMS daily cap exceeded ({current_count}/{cap})",
            html=html,
            text=text,
        )
        logger.info("[sms_quota] cap-exceeded alert sent to %s", alert_to)
    except Exception as e:
        # send_alert already swallows HTTP errors, but be defensive.
        logger.exception("[sms_quota] alert email dispatch failed: %s", e)
