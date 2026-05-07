"""Replace dead lumi-unt.kz image URLs in `subjects.image` with new
PNG icons hosted in our MinIO bucket.

Safety net:
  1. Saves current (id, name, image) tuples to /tmp/subjects_backup_<ts>.json
     before any write — restoring is one INSERT-script away.
  2. Uses a single Postgres transaction.  If any UPDATE fails, the
     whole batch rolls back; nothing is committed unless every URL
     also returns HTTP 200 in a post-flight smoke check.

Icons come from icons8 free CDN (black on transparent, 96x96 PNG).
Flutter renders them with `color: Colors.white`, which tints all
non-transparent pixels — so a black source produces a white silhouette.
"""

import io
import json
import os
import sys
import time
import urllib.request

import psycopg
import requests
from minio import Minio
from minio.error import S3Error

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: set DATABASE_URL"); sys.exit(1)

MINIO_HOST = "minio-production-24ed.up.railway.app"
MINIO_ACCESS = "8DIGUUC4A3ZZTTFNDTV1"
MINIO_SECRET = "dBtVEUu+3Cjp2+xkA3XXHBVwv8Btzoe4y8y12RMW"
MINIO_BUCKET = "aima-uploads"

# Storage path inside the bucket. The avatar logic uses `avatars/`,
# subject icons get their own folder so admin tools listing each
# category stay clean.
SUBJECT_PREFIX = "subjects"

# Map subject name → (filename, icons8 URL).  icons8 PNGs are 96x96
# black-on-transparent; Flutter applies a white tint at render time.
ICON_MAP = {
    "Физика":                       ("physics.png",       "https://img.icons8.com/material-rounded/96/000000/physics.png"),
    "Химия":                        ("chemistry.png",     "https://img.icons8.com/material-rounded/96/000000/test-tube.png"),
    "Математика":                   ("math.png",          "https://img.icons8.com/material-rounded/96/000000/calculator.png"),
    "Математическая грамотность":   ("math_literacy.png", "https://img.icons8.com/material-rounded/96/000000/sigma.png"),
    "Биология":                     ("biology.png",       "https://img.icons8.com/material-rounded/96/000000/dna-helix.png"),
    "География":                    ("geography.png",     "https://img.icons8.com/material-rounded/96/000000/globe-earth.png"),
    "Информатика":                  ("informatics.png",   "https://img.icons8.com/material-rounded/96/000000/source-code.png"),
    "Английский":                   ("english.png",       "https://img.icons8.com/material-rounded/96/000000/translation.png"),
    "Грамотность чтения":           ("reading.png",       "https://img.icons8.com/material-rounded/96/000000/book.png"),
    "Всемирная История":            ("world_history.png", "https://img.icons8.com/material-rounded/96/000000/time-machine.png"),
    "История Казахстана":           ("kz_history.png",    "https://img.icons8.com/material-rounded/96/000000/museum.png"),
    "Основы Права":                 ("law.png",           "https://img.icons8.com/material-rounded/96/000000/scales.png"),
}


def backup_subjects() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/subjects_backup_{ts}.json"
    rows: list[dict] = []
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, image FROM subjects ORDER BY id")
            for id_, name, image in cur.fetchall():
                rows.append({"id": id_, "name": name, "image": image})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"✅ backup saved: {path} ({len(rows)} rows)")
    return path


def download_icon(url: str) -> bytes:
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AIMA-seeder/1.0)"},
        timeout=30,
        allow_redirects=True,
    )
    r.raise_for_status()
    if not r.content:
        raise RuntimeError(f"empty body from {url}")
    return r.content


def upload_to_minio(client: Minio, filename: str, payload: bytes) -> str:
    storage_key = f"{SUBJECT_PREFIX}/{filename}"
    client.put_object(
        MINIO_BUCKET,
        storage_key,
        io.BytesIO(payload),
        len(payload),
        content_type="image/png",
    )
    return storage_key


def verify_presigned(client: Minio, storage_key: str) -> bool:
    """Generates a presigned URL and HEAD-checks reachability."""
    from datetime import timedelta
    url = client.presigned_get_object(MINIO_BUCKET, storage_key, expires=timedelta(minutes=5))
    try:
        # GET is more reliable than HEAD against MinIO presigned URLs.
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    print(">>> Step 1: backup current subjects.image values")
    backup_path = backup_subjects()

    minio_client = Minio(MINIO_HOST, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET, secure=True)

    print("\n>>> Step 2: download icons + upload to MinIO")
    upload_results: dict[str, str] = {}  # subject name → storage_key
    for subject_name, (filename, url) in ICON_MAP.items():
        payload = download_icon(url)
        key = upload_to_minio(minio_client, filename, payload)
        upload_results[subject_name] = key
        print(f"  ✓ {subject_name}: uploaded {key} ({len(payload)} bytes)")

    print("\n>>> Step 3: smoke-test presigned URLs")
    for subject_name, key in upload_results.items():
        ok = verify_presigned(minio_client, key)
        mark = "✓" if ok else "✗"
        print(f"  {mark} {subject_name}: {key}")
        if not ok:
            print("ABORT: presigned URL returned non-200; nothing committed.")
            sys.exit(1)

    print("\n>>> Step 4: UPDATE subjects.image inside a single transaction")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for subject_name, (filename, _) in ICON_MAP.items():
                cur.execute(
                    "UPDATE subjects SET image = %s WHERE name = %s",
                    (filename, subject_name),
                )
                if cur.rowcount == 0:
                    print(f"  WARN: no row matched for {subject_name!r}")
                else:
                    print(f"  ✓ {subject_name} → image = {filename}")
        conn.commit()

    print(f"\n✅ Done.  Rollback if needed: re-run the original "
          f"image values from {backup_path}")


if __name__ == "__main__":
    main()
