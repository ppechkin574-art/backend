"""Free IP geolocation via ip-api.com (no API key, 45 req/min).

Used for login security events — shows city in the push notification
and fraud event metadata. All calls are best-effort with a short timeout;
failures silently return None so they never affect the login flow.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 3.0  # seconds — never block login for geo lookup
_URL = "http://ip-api.com/json/{ip}?fields=status,city,country,regionName"

# IPs that are meaningless to look up
_PRIVATE_PREFIXES = (
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.", "::1", "fc", "fd",
)


def get_client_ip(request_headers: dict, client_host: str | None) -> str | None:
    """Extract real client IP from X-Forwarded-For or X-Real-IP (Railway/nginx)."""
    forwarded = request_headers.get("x-forwarded-for") or request_headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    real_ip = request_headers.get("x-real-ip") or request_headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return client_host


def lookup_city(ip: str | None) -> str | None:
    """Return 'City, Country' string for an IP, or None on any failure."""
    if not ip:
        return None
    if any(ip.startswith(p) for p in _PRIVATE_PREFIXES):
        return None
    try:
        resp = httpx.get(_URL.format(ip=ip), timeout=_TIMEOUT)
        data = resp.json()
        if data.get("status") != "success":
            return None
        city = data.get("city", "")
        country = data.get("country", "")
        parts = [p for p in [city, country] if p]
        return ", ".join(parts) if parts else None
    except Exception as exc:
        logger.debug("GeoIP lookup failed for %s: %s", ip, exc)
        return None
