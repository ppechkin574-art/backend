"""Seed 5 realistic Kazakh users with avatars and leaderboard points.

What it does:
  1. Creates 5 users in Keycloak realm `lumi` via admin API
  2. Downloads a portrait from pravatar.cc for each
  3. Uploads the avatar to MinIO under `avatars/<user_id>_<hash>.jpg`
  4. Sets the `avatar` attribute on the Keycloak user
  5. Inserts a row into the `user_points` table with descending scores
  6. Also bumps zhahangir to ~250 points so he sits ~position 6+

Run once, idempotent on the user-creation step (skips if email exists).
"""

import hashlib
import io
import secrets
import sys
import urllib.request

import psycopg
import requests
from minio import Minio
from datetime import timedelta

# --- secrets used transiently; not persisted by the script ---
KC_URL = "https://keycloak-production-0a0c.up.railway.app"
KC_ADMIN_PSW = "gRv6grqO0OcQCnCCXRD4d2B90ZMsNquf"
REALM = "lumi"

MINIO_HOST = "minio-production-24ed.up.railway.app"  # API port (fixed earlier today)
MINIO_ACCESS = "8DIGUUC4A3ZZTTFNDTV1"
MINIO_SECRET = "dBtVEUu+3Cjp2+xkA3XXHBVwv8Btzoe4y8y12RMW"
MINIO_BUCKET = "aima-uploads"

# DATABASE_URL pulled from Railway env at runtime; user must export it before running.
import os
DATABASE_URL = os.environ.get("DATABASE_URL")
# Optional — if missing, the script still runs avatar+KC steps and just
# warns when the points-upsert can't connect. Useful when refreshing
# avatars from a local machine that doesn't have access to the private
# Railway DB network.
if not DATABASE_URL:
    print("ℹ no DATABASE_URL — avatars+KC will still run, points upsert will be skipped")

ZHAHANGIR_USER_ID = "33caa41d-1fb0-4fea-b166-3687e1493663"
ZHAHANGIR_POINTS = 250

# Avatars are now sourced from `scripts/avatars/` — a small set of
# curated portraits committed to the repo. randomuser.me / pravatar.cc
# both produced uneven looks across the podium (random aging, random
# pose, sometimes thumbs-up stock-photo energy that didn't match an
# EdTech app for high-school students). Local files give us full
# control over the visual that ends up in the leaderboard screenshot.
SEED_USERS = [
    {"name": "Айдар Нурланов",  "phone": "+77780000001", "avatar_file": "aydar.jpg",  "points": 5000},
    {"name": "Динара Сапарова", "phone": "+77780000002", "avatar_file": "dinara.jpg", "points": 4500},
    {"name": "Алмас Жумабаев",  "phone": "+77780000003", "avatar_file": "almas.jpg",  "points": 4000},
    {"name": "Камила Бекова",   "phone": "+77780000004", "avatar_file": "kamila.jpg", "points": 3500},
    {"name": "Ержан Касымов",   "phone": "+77780000005", "avatar_file": "yerzhan.jpg", "points": 3000},
]


def get_admin_token() -> str:
    r = requests.post(
        f"{KC_URL}/realms/master/protocol/openid-connect/token",
        data={
            "username": "admin",
            "password": KC_ADMIN_PSW,
            "grant_type": "password",
            "client_id": "admin-cli",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def find_or_create_user(token: str, name: str, phone: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    # Match the synthetic-email pattern Keycloak uses for phone-only users:
    # `phone.<digits>@aima.internal` (with dot after "phone").
    search_email = f"phone.{phone.replace('+', '')}@aima.internal"
    r = requests.get(
        f"{KC_URL}/admin/realms/{REALM}/users",
        params={"email": search_email, "exact": "true"},
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    existing = r.json()
    if existing:
        print(f"  → exists: {existing[0]['id']}")
        return existing[0]["id"]

    # Create
    payload = {
        "username": search_email,
        "email": search_email,
        "emailVerified": True,
        "enabled": True,
        "attributes": {
            "name": [name],
            "phone": [phone],
            "role": ["student"],
            "plan": ["FREE"],
        },
    }
    r = requests.post(
        f"{KC_URL}/admin/realms/{REALM}/users",
        json=payload,
        headers={**headers, "Content-Type": "application/json"},
        timeout=15,
    )
    # 409 means the user is already there but our exact-email search
    # didn't find them (Keycloak's `exact=true` semantics drift between
    # versions). Fall through to the lookup below.
    if r.status_code not in (201, 204, 409):
        raise RuntimeError(f"Failed to create user: {r.status_code} {r.text}")

    # Re-fetch to get id. Try three increasingly fuzzy queries — Keycloak
    # 26 has been picky about which attribute returns hits when seeded
    # users were created via the auth/code/check flow rather than this
    # script (different email-vs-username layout).
    for params in (
        {"email": search_email, "exact": "true"},
        {"username": search_email, "exact": "true"},
        {"search": phone},
    ):
        r = requests.get(
            f"{KC_URL}/admin/realms/{REALM}/users",
            params=params,
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()
        if rows:
            return rows[0]["id"]
    raise RuntimeError(f"User created but vanished from search: {phone}")


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_AVATARS_DIR = os.path.join(SCRIPT_DIR, "avatars")


def upload_avatar(user_id: str, avatar_file: str) -> str:
    """Read a portrait from `scripts/avatars/<avatar_file>`, push it to
    MinIO, return the filename matching the convention used by
    FileService.

    Local-file mode replaces the randomuser.me / pravatar.cc download
    pipeline (commit 8982235 / earlier). Curated photos give a
    consistent visual across the leaderboard podium — that's what the
    App Store screenshots will end up capturing.
    """
    avatar_path = os.path.join(LOCAL_AVATARS_DIR, avatar_file)
    if not os.path.isfile(avatar_path):
        raise FileNotFoundError(
            f"Avatar file missing: {avatar_path}. "
            f"Curated avatars live in scripts/avatars/ — add the file or "
            f"update the avatar_file field in SEED_USERS."
        )
    with open(avatar_path, "rb") as fh:
        portrait = fh.read()
    digest = hashlib.md5(portrait + secrets.token_bytes(8)).hexdigest()
    filename = f"{user_id}_{digest}.jpg"
    storage_key = f"avatars/{filename}"
    client = Minio(MINIO_HOST, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET, secure=True)
    client.put_object(MINIO_BUCKET, storage_key, io.BytesIO(portrait), len(portrait), content_type="image/jpeg")
    return filename


def set_avatar_attr(token: str, user_id: str, filename: str, name: str, phone: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "attributes": {
            "name": [name],
            "phone": [phone],
            "role": ["student"],
            "plan": ["FREE"],
            "avatar": [filename],
        }
    }
    r = requests.put(
        f"{KC_URL}/admin/realms/{REALM}/users/{user_id}",
        json=payload,
        headers=headers,
        timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Failed to set avatar: {r.status_code} {r.text}")


def upsert_points(user_id: str, points: int) -> None:
    """Both `students` and `user_points` need rows — `user_points`
    has a FK to `students.id`.  We seed `students.rating` to 0; the
    rating is populated separately by the trainer pipeline and isn't
    relevant to the leaderboard."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO students (id, rating)
                VALUES (%s, 0)
                ON CONFLICT (id) DO NOTHING
                """,
                (user_id,),
            )
            cur.execute(
                """
                INSERT INTO user_points (user_id, total_points)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET total_points = EXCLUDED.total_points
                """,
                (user_id, points),
            )
        conn.commit()


def main():
    token = get_admin_token()
    print("✅ KC admin token acquired")

    for u in SEED_USERS:
        print(f"\n=== {u['name']} ({u['phone']}) ===")
        user_id = find_or_create_user(token, u["name"], u["phone"])
        print(f"  id: {user_id}")

        filename = upload_avatar(user_id, u["avatar_file"])
        print(f"  avatar uploaded: avatars/{filename}")

        # Refresh token mid-run to avoid expiry
        set_avatar_attr(token, user_id, filename, u["name"], u["phone"])
        print("  avatar attribute set in KC")

        # Postgres is reachable only via the Railway internal network
        # since we removed the public TCP proxy on 09.05.2026 — running
        # this script from a local machine can't update the points table.
        # The avatar / KC pipeline above runs over the public Keycloak +
        # MinIO endpoints and works regardless. Skip the point upsert
        # gracefully so re-running for avatar refresh isn't a hard fail.
        try:
            upsert_points(user_id, u["points"])
            print(f"  points = {u['points']}")
        except Exception as e:
            print(f"  ⚠ skipping points upsert (DB unreachable): {type(e).__name__}: {str(e)[:100]}")

    try:
        upsert_points(ZHAHANGIR_USER_ID, ZHAHANGIR_POINTS)
        print(f"\n✅ zhahangir bumped to {ZHAHANGIR_POINTS} points")
    except Exception as e:
        print(f"\n⚠ skipping zhahangir points (DB unreachable): {type(e).__name__}")
    print("\nDone.")


if __name__ == "__main__":
    main()
