"""Seed phantom fraud events and risk profiles for demo/testing.

Inserts realistic-looking fraud data so the Security section in admin
shows a populated list. All user_ids are fake UUIDs that don't correspond
to real Keycloak users — they will show as "—" in the UI.

Usage (from backend/ directory):
    DATABASE_URL="postgresql://..." python scripts/seed_fraud_demo.py

Or with Railway DATABASE_PUBLIC_URL already set:
    python scripts/seed_fraud_demo.py
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
if not DATABASE_URL:
    print("ERROR: set DATABASE_URL or DATABASE_PUBLIC_URL env var")
    sys.exit(1)

# Replace asyncpg/sqlalchemy URL format with psycopg2-compatible one
DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

NOW = datetime.now(tz=UTC)

# ---------------------------------------------------------------------------
# Phantom user IDs (fake, not in Keycloak)
# ---------------------------------------------------------------------------
USERS = [
    uuid.UUID("aaaaaaaa-0001-0001-0001-000000000001"),
    uuid.UUID("aaaaaaaa-0002-0002-0002-000000000002"),
    uuid.UUID("aaaaaaaa-0003-0003-0003-000000000003"),
    uuid.UUID("aaaaaaaa-0004-0004-0004-000000000004"),
    uuid.UUID("aaaaaaaa-0005-0005-0005-000000000005"),
]

# ---------------------------------------------------------------------------
# Fraud events
# ---------------------------------------------------------------------------
EVENTS = [
    # Critical — rapid points farm
    dict(
        user_id=USERS[0], event_type="rapid_points_farm", risk_score=92,
        reason="Attempt #demo-1: 20 questions in 18s (0.9s/q < 5s/q threshold)",
        ip_address="95.142.40.11", status="open",
        created_at=NOW - timedelta(hours=1),
        metadata={"attempt_id": "demo-1", "spend_time": 18, "total_questions": 20},
    ),
    dict(
        user_id=USERS[0], event_type="bot_speed_answers", risk_score=88,
        reason="Median answer time 1.3s across 15 questions (threshold: 2s)",
        ip_address="95.142.40.11", status="open",
        created_at=NOW - timedelta(minutes=50),
        metadata={"median_ms": 1300},
    ),
    # High — pattern answers
    dict(
        user_id=USERS[1], event_type="pattern_answers", risk_score=78,
        reason="Answer position A selected in 84% of questions (threshold: 80%)",
        ip_address="212.109.3.77", status="open",
        created_at=NOW - timedelta(hours=3),
        metadata={"position": "A", "pct": 84},
    ),
    dict(
        user_id=USERS[1], event_type="rapid_points_farm", risk_score=71,
        reason="Attempt #demo-2: 25 questions in 32s (1.3s/q < 5s/q threshold)",
        ip_address="212.109.3.77", status="open",
        created_at=NOW - timedelta(hours=2, minutes=30),
        metadata={"attempt_id": "demo-2", "spend_time": 32, "total_questions": 25},
    ),
    # Suspicious login
    dict(
        user_id=USERS[2], event_type="suspicious_login", risk_score=65,
        reason="Login from Almaty — previous session was Astana 2h ago",
        ip_address="178.89.101.5", status="open",
        created_at=NOW - timedelta(hours=5),
        metadata={"prev_city": "Astana", "new_city": "Almaty", "gap_hours": 2},
    ),
    # Brute force
    dict(
        user_id=USERS[3], event_type="brute_force", risk_score=85,
        reason="43 failed Keycloak login attempts in 5 minutes from same IP",
        ip_address="91.227.33.244", status="open",
        created_at=NOW - timedelta(hours=7),
        metadata={"attempts": 43, "window_minutes": 5},
    ),
    # Concurrent submission
    dict(
        user_id=USERS[4], event_type="concurrent_submission", risk_score=60,
        reason="Attempt #demo-3 submitted from 2 different IPs within 200ms",
        ip_address="5.188.62.99", status="open",
        created_at=NOW - timedelta(hours=10),
        metadata={"attempt_id": "demo-3", "ip_count": 2, "gap_ms": 200},
    ),
    # Already reviewed examples
    dict(
        user_id=USERS[2], event_type="repeated_attempt", risk_score=55,
        reason="Attempt re-submitted after 3 minutes (likely page refresh)",
        ip_address="178.89.101.5", status="reviewed",
        created_at=NOW - timedelta(days=1),
        reviewed_at=NOW - timedelta(hours=23),
        reviewed_by="admin@aima.kz",
        metadata={},
    ),
]

# ---------------------------------------------------------------------------
# Risk profiles
# ---------------------------------------------------------------------------
PROFILES = [
    dict(user_id=USERS[0], current_risk_score=92, status="normal",
         total_suspicious_events=4, is_watchlisted=True,
         points_frozen=True, referral_disabled=False,
         last_suspicious_activity_at=NOW - timedelta(minutes=50)),
    dict(user_id=USERS[1], current_risk_score=78, status="restricted",
         restriction_reason="Pattern answers + rapid farm — restricted by admin",
         restricted_until=NOW + timedelta(days=3),
         total_suspicious_events=3, is_watchlisted=True,
         points_frozen=True, referral_disabled=True,
         last_suspicious_activity_at=NOW - timedelta(hours=2)),
    dict(user_id=USERS[2], current_risk_score=65, status="normal",
         total_suspicious_events=2, is_watchlisted=True,
         points_frozen=False, referral_disabled=False,
         last_suspicious_activity_at=NOW - timedelta(hours=5)),
    dict(user_id=USERS[3], current_risk_score=85, status="blocked",
         restriction_reason="Brute force attack — blocked by admin",
         blocked_at=NOW - timedelta(hours=6),
         total_suspicious_events=1, is_watchlisted=False,
         points_frozen=False, referral_disabled=False,
         last_suspicious_activity_at=NOW - timedelta(hours=7)),
    dict(user_id=USERS[4], current_risk_score=60, status="normal",
         total_suspicious_events=1, is_watchlisted=False,
         points_frozen=False, referral_disabled=False,
         last_suspicious_activity_at=NOW - timedelta(hours=10)),
]


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def insert_events():
    inserted = 0
    skipped = 0
    for e in EVENTS:
        cur.execute(
            "SELECT id FROM fraud_events WHERE user_id = %s AND event_type = %s AND reason = %s",
            (str(e["user_id"]), e["event_type"], e["reason"]),
        )
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute(
            """INSERT INTO fraud_events
               (user_id, event_type, risk_score, reason, ip_address, status,
                created_at, reviewed_at, reviewed_by, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
            (
                str(e["user_id"]),
                e["event_type"],
                e["risk_score"],
                e["reason"],
                e.get("ip_address"),
                e.get("status", "open"),
                e.get("created_at", NOW),
                e.get("reviewed_at"),
                e.get("reviewed_by"),
                __import__("json").dumps(e.get("metadata", {})),
            ),
        )
        inserted += 1
    print(f"  fraud_events: {inserted} inserted, {skipped} skipped (already exist)")


def insert_profiles():
    inserted = 0
    skipped = 0
    for p in PROFILES:
        cur.execute(
            "SELECT id FROM user_risk_profiles WHERE user_id = %s",
            (str(p["user_id"]),),
        )
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute(
            """INSERT INTO user_risk_profiles
               (user_id, current_risk_score, status, restriction_reason,
                restricted_until, blocked_at, total_suspicious_events,
                is_watchlisted, points_frozen, referral_disabled,
                last_suspicious_activity_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                str(p["user_id"]),
                p.get("current_risk_score", 0),
                p.get("status", "normal"),
                p.get("restriction_reason"),
                p.get("restricted_until"),
                p.get("blocked_at"),
                p.get("total_suspicious_events", 0),
                p.get("is_watchlisted", False),
                p.get("points_frozen", False),
                p.get("referral_disabled", False),
                p.get("last_suspicious_activity_at"),
            ),
        )
        inserted += 1
    print(f"  user_risk_profiles: {inserted} inserted, {skipped} skipped (already exist)")


print("Seeding phantom fraud demo data...")
try:
    insert_events()
    insert_profiles()
    conn.commit()
    print("Done. Open admin → Security to see the demo data.")
except Exception as exc:
    conn.rollback()
    print(f"ERROR: {exc}")
    sys.exit(1)
finally:
    cur.close()
    conn.close()
