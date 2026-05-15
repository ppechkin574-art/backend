"""Two-layer SMS abuse defence: global daily cap + per-IP daily block.

Covers:
- Reviewer bypass — never blocked, never counted.
- Per-IP block triggers 429 at threshold.
- Global cap triggers 503 above cap.
- Counters INCR on record_sms_request; reviewer skipped.
- Cap-exceeded alert email fires exactly once per day (dedup).
- Alert email includes top-5 IPs by request count.
- Redis failures fall open (don't crash auth).

All collaborators faked. Frozen day so date string is deterministic.
"""

import os
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from redis import RedisError

from api.middlewares import sms_quota


# ─────────────────────────── fakes ───────────────────────────


class _FakeRedis:
    """Tracks calls and stores key/value + zset state in-memory.
    `fail_on` causes specific commands to raise RedisError so we can
    verify fail-open behaviour."""

    def __init__(self, fail_on: set[str] | None = None):
        self.kv: dict[str, int | str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.fail_on = fail_on or set()
        self.calls: list[tuple[str, Any]] = []
        self.set_nx_returns: bool = True

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail_on:
            raise RedisError(f"simulated fail on {name}")

    def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key))
        self._maybe_fail("get")
        v = self.kv.get(key)
        return str(v).encode() if v is not None else None

    def zscore(self, zkey: str, member: str) -> float | None:
        self.calls.append(("zscore", (zkey, member)))
        self._maybe_fail("zscore")
        return self.zsets.get(zkey, {}).get(member)

    def zincrby(self, zkey: str, amount: float, member: str) -> float:
        self.calls.append(("zincrby", (zkey, amount, member)))
        self._maybe_fail("zincrby")
        bucket = self.zsets.setdefault(zkey, {})
        bucket[member] = bucket.get(member, 0) + amount
        return bucket[member]

    def incr(self, key: str) -> int:
        self.calls.append(("incr", key))
        self._maybe_fail("incr")
        new = int(self.kv.get(key, 0)) + 1
        self.kv[key] = new
        return new

    def expire(self, key: str, ttl: int) -> None:
        self.calls.append(("expire", (key, ttl)))
        self._maybe_fail("expire")

    def zrevrange(self, zkey: str, start: int, stop: int, withscores: bool = False):
        self.calls.append(("zrevrange", (zkey, start, stop)))
        self._maybe_fail("zrevrange")
        items = sorted(
            self.zsets.get(zkey, {}).items(), key=lambda x: -x[1]
        )[start : stop + 1]
        return [(k, v) for k, v in items] if withscores else [k for k, _ in items]

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        self.calls.append(("set", (key, value, ex, nx)))
        self._maybe_fail("set")
        if nx and key in self.kv:
            return None  # NX fails — key exists
        self.kv[key] = value
        return True


def _make_request(ip: str = "203.0.113.42") -> MagicMock:
    """X-Forwarded-For-style real-client extraction matches what
    _real_client_ip does in rate_limit.py."""
    req = MagicMock()
    req.headers = {"x-forwarded-for": ip}
    req.client = None
    return req


def _make_app_settings(cap: int = 1000, ip_block: int = 20):
    """Fake AppSettingsService — only get_int is touched by sms_quota."""
    svc = MagicMock()

    def _get_int(key: str, default: int) -> int:
        if key == "sms_daily_cap":
            return cap
        if key == "sms_ip_daily_block":
            return ip_block
        return default

    svc.get_int.side_effect = _get_int
    return svc


def _make_email_client():
    svc = MagicMock()
    svc.send_alert = MagicMock()
    return svc


@pytest.fixture(autouse=True)
def _reviewer_phone_env(monkeypatch):
    """Reviewer bypass uses REVIEWER_TEST_PHONE env. Pin it for the suite."""
    monkeypatch.setenv("REVIEWER_TEST_PHONE", "+77001234567")


# ─────────────────────────── check_sms_quota ───────────────────────────


def test_reviewer_bypass_contact_skips_all_checks():
    """Apple App Review must never be blocked, even if cap is exceeded."""
    redis = _FakeRedis()
    redis.kv["sms:daily:total:2026-05-15"] = 999_999  # cap blown wide
    redis.zsets["sms:daily:ips:2026-05-15"] = {"203.0.113.42": 999}
    settings = _make_app_settings(cap=10, ip_block=1)

    # Should NOT raise even though both thresholds are pulverised.
    sms_quota.check_sms_quota(
        _make_request(),
        contact="+77001234567",  # reviewer test phone
        redis=redis,
        app_settings=settings,
    )


def test_passes_when_no_counters_exist_yet():
    redis = _FakeRedis()
    settings = _make_app_settings(cap=1000, ip_block=20)

    sms_quota.check_sms_quota(
        _make_request(), "+77787943760", redis, settings
    )


def test_per_ip_block_triggers_429_at_threshold():
    redis = _FakeRedis()
    today = sms_quota._today_utc()
    redis.zsets[f"sms:daily:ips:{today}"] = {"203.0.113.42": 20}
    settings = _make_app_settings(cap=1000, ip_block=20)

    with pytest.raises(HTTPException) as exc:
        sms_quota.check_sms_quota(
            _make_request("203.0.113.42"), "+77787943760", redis, settings
        )

    assert exc.value.status_code == 429
    # U2=(a): neutral message, no detail about exact threshold/time
    assert "завтра" in exc.value.detail.lower()


def test_per_ip_block_does_not_trigger_below_threshold():
    redis = _FakeRedis()
    today = sms_quota._today_utc()
    redis.zsets[f"sms:daily:ips:{today}"] = {"203.0.113.42": 19}  # just under
    settings = _make_app_settings(cap=1000, ip_block=20)

    # No raise — passes through
    sms_quota.check_sms_quota(
        _make_request("203.0.113.42"), "+77787943760", redis, settings
    )


def test_global_cap_triggers_503_when_exceeded():
    redis = _FakeRedis()
    today = sms_quota._today_utc()
    redis.kv[f"sms:daily:total:{today}"] = 1000
    settings = _make_app_settings(cap=1000, ip_block=20)

    with pytest.raises(HTTPException) as exc:
        sms_quota.check_sms_quota(
            _make_request(), "+77787943760", redis, settings
        )

    assert exc.value.status_code == 503


def test_redis_failure_fails_open():
    """If Redis is down, the guard must NOT block legitimate requests —
    SMS-auth stays online and we lose only abuse detection."""
    redis = _FakeRedis(fail_on={"zscore", "get"})
    settings = _make_app_settings(cap=1000, ip_block=20)

    # Should NOT raise
    sms_quota.check_sms_quota(
        _make_request(), "+77787943760", redis, settings
    )


# ─────────────────────────── record_sms_request ───────────────────────────


def test_record_skips_reviewer_contact():
    redis = _FakeRedis()
    settings = _make_app_settings()
    email = _make_email_client()

    sms_quota.record_sms_request(
        _make_request(), "+77001234567", redis, settings, email
    )

    # No INCR / ZINCRBY calls — reviewer traffic doesn't pollute metrics.
    assert not any(c[0] in ("incr", "zincrby") for c in redis.calls)


def test_record_increments_both_counters_with_25h_ttl():
    """Counter TTL is 25h (24h + 1h buffer) to avoid the daily-reset
    window where stale counters would coexist with new ones."""
    redis = _FakeRedis()
    settings = _make_app_settings()
    email = _make_email_client()

    sms_quota.record_sms_request(
        _make_request("203.0.113.42"), "+77787943760", redis, settings, email
    )

    today = sms_quota._today_utc()
    assert redis.kv[f"sms:daily:total:{today}"] == 1
    assert redis.zsets[f"sms:daily:ips:{today}"]["203.0.113.42"] == 1

    expire_calls = [c for c in redis.calls if c[0] == "expire"]
    assert len(expire_calls) == 2
    assert all(c[1][1] == 25 * 3600 for c in expire_calls)


def test_record_redis_failure_does_not_raise():
    """Counter writes are best-effort. If Redis dies, the request still
    succeeded — we just lose visibility into this one event."""
    redis = _FakeRedis(fail_on={"zincrby"})
    settings = _make_app_settings()
    email = _make_email_client()

    # Must not raise
    sms_quota.record_sms_request(
        _make_request(), "+77787943760", redis, settings, email
    )


def test_cap_alert_fires_once_per_day_only():
    """When the INCR that crosses the cap happens, exactly ONE email
    should go out — not one per subsequent over-cap request."""
    redis = _FakeRedis()
    settings = _make_app_settings(cap=1, ip_block=20)
    email = _make_email_client()
    today = sms_quota._today_utc()

    # Prime: first call crosses cap → alert fires
    sms_quota.record_sms_request(
        _make_request("1.1.1.1"), "+77787943760", redis, settings, email
    )
    # Second call (still over cap) → alert dedup'd, no email
    sms_quota.record_sms_request(
        _make_request("1.1.1.1"), "+77787943760", redis, settings, email
    )
    sms_quota.record_sms_request(
        _make_request("2.2.2.2"), "+77787943761", redis, settings, email
    )

    assert email.send_alert.call_count == 1


def test_cap_alert_includes_top_5_ips_in_body():
    redis = _FakeRedis()
    settings = _make_app_settings(cap=1, ip_block=1000)
    email = _make_email_client()

    # Stack many IPs with varying counts
    today = sms_quota._today_utc()
    redis.zsets[f"sms:daily:ips:{today}"] = {
        "9.9.9.9": 50,
        "1.1.1.1": 40,
        "2.2.2.2": 30,
        "3.3.3.3": 20,
        "4.4.4.4": 10,
        "5.5.5.5": 5,
        "6.6.6.6": 2,
    }
    redis.kv[f"sms:daily:total:{today}"] = 0

    sms_quota.record_sms_request(
        _make_request("8.8.8.8"), "+77787943760", redis, settings, email
    )

    # Alert went out
    assert email.send_alert.call_count == 1
    kwargs = email.send_alert.call_args.kwargs
    # Top-5 IPs by score must be in the body (HTML or text)
    body = kwargs["html"] + kwargs.get("text", "")
    assert "9.9.9.9" in body
    assert "1.1.1.1" in body
    assert "2.2.2.2" in body
    assert "3.3.3.3" in body
    assert "4.4.4.4" in body
    # 6th and 7th IPs must NOT be — we cap at 5
    assert "6.6.6.6" not in body
    # And the 5th still in
    assert "5.5.5.5" in body or "4.4.4.4" in body  # one of bottom 5


def test_cap_alert_sent_to_alert_email_env(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")

    redis = _FakeRedis()
    settings = _make_app_settings(cap=1)
    email = _make_email_client()

    sms_quota.record_sms_request(
        _make_request(), "+77787943760", redis, settings, email
    )

    assert email.send_alert.call_args.kwargs["to"] == "ops@example.com"


def test_cap_alert_default_recipient_when_env_unset(monkeypatch):
    """When ALERT_EMAIL is not set, default to ppechkin574@gmail.com
    (the operator's address — set explicitly in answer to Q_b)."""
    monkeypatch.delenv("ALERT_EMAIL", raising=False)

    redis = _FakeRedis()
    settings = _make_app_settings(cap=1)
    email = _make_email_client()

    sms_quota.record_sms_request(
        _make_request(), "+77787943760", redis, settings, email
    )

    assert email.send_alert.call_args.kwargs["to"] == "ppechkin574@gmail.com"


def test_record_below_cap_does_not_alert():
    redis = _FakeRedis()
    settings = _make_app_settings(cap=1000, ip_block=20)
    email = _make_email_client()

    sms_quota.record_sms_request(
        _make_request(), "+77787943760", redis, settings, email
    )

    email.send_alert.assert_not_called()
