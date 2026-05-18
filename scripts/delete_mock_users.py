#!/usr/bin/env python3
"""Delete the 5 seed-mock leaderboard users from production Keycloak.

The named mocks (Айдар Нурланов / Динара Сапарова / Алмас Жумабаев /
Камила Бекова / Ержан Касымов) were created on 08.05.2026 with the
sequential phone block +77780000001..+77780000005 to populate the
leaderboard during early development. They now show up as fake Top-3
on the live App Store build and need to come out. Backend has
DELETE /admin/users/{id} but the admin panel UI doesn't expose it
yet, so we go through the API directly.

Usage:
    cd aima-backend
    python3 scripts/delete_mock_users.py
    # ↳ prompts for admin email + password interactively
    #   (defaults email to admin@aima.kz, password input is hidden).

    # Or non-interactive (CI / repeated runs) via env vars:
    AIMA_ADMIN_EMAIL='admin@aima.kz' \
    AIMA_ADMIN_PASSWORD='...' \
    python3 scripts/delete_mock_users.py

What it does:
    1. Logs in as the admin via /auth/login-swagger (OAuth2 password
       grant — same path the swagger UI uses)
    2. Lists all users via /admin/users
    3. Filters to the 5 mock numbers above
    4. Prints them for confirmation; asks y/n
    5. DELETE /admin/users/{id} for each, reports per-row result

Safety:
    - Asks for confirmation BEFORE deleting anything
    - Skips any user whose phone is outside the mock block — even if
      the name partially matches a real user
    - Idempotent: re-running after a successful delete is a no-op
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any


BACKEND = "https://backend-production-f2a1.up.railway.app"

MOCK_PHONES = {
    "+77780000001",
    "+77780000002",
    "+77780000003",
    "+77780000004",
    "+77780000005",
}


def _http(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    form_body: dict | None = None,
) -> tuple[int, Any]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(
        f"{BACKEND}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body) if body else None
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body) if body else None
        except json.JSONDecodeError:
            return e.code, body


def login(email: str, password: str) -> str:
    """OAuth2 password grant via /auth/login-swagger.

    Returns access_token. Raises on any failure with a readable
    message so the operator knows what to fix (wrong password,
    user disabled, etc.).
    """
    status, body = _http(
        "POST",
        "/auth/login-swagger",
        form_body={"username": email, "password": password, "grant_type": "password"},
    )
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        sys.exit(
            f"Login failed: HTTP {status} body={body!r}\n"
            "Check AIMA_ADMIN_EMAIL/AIMA_ADMIN_PASSWORD env vars."
        )
    return body["access_token"]


def list_users(token: str) -> list[dict]:
    status, body = _http("GET", "/admin/users", token=token)
    if status != 200 or not isinstance(body, list):
        sys.exit(f"List users failed: HTTP {status} body={body!r}")
    return body


def delete_user(token: str, user_id: str) -> tuple[int, Any]:
    return _http("DELETE", f"/admin/users/{user_id}", token=token)


def main() -> None:
    # Allow env-var override (CI / repeated runs) but fall back to
    # interactive prompts so a single `python3 scripts/...` invocation
    # works for an operator who's never seen the script before. This
    # also avoids the previous copy-paste trap where the placeholder
    # text in the README leaked into the password field.
    email = os.getenv("AIMA_ADMIN_EMAIL")
    if not email:
        email = input("Admin email [admin@aima.kz]: ").strip() or "admin@aima.kz"
    password = os.getenv("AIMA_ADMIN_PASSWORD")
    if not password:
        # getpass hides keystrokes — safer than input() for secrets
        password = getpass.getpass(f"Password for {email}: ")
    if not password:
        sys.exit("Empty password, aborted.")

    print(f"→ logging in as {email}...")
    token = login(email, password)
    print("✓ logged in")

    print("→ listing users...")
    users = list_users(token)
    print(f"✓ {len(users)} users in keycloak")

    targets: list[dict] = []
    for u in users:
        phone = u.get("phone")
        if phone in MOCK_PHONES:
            targets.append(u)

    if not targets:
        print("\nNo mock users found — already deleted, nothing to do.")
        return

    print(f"\nFound {len(targets)} mock users to delete:")
    for u in targets:
        print(f"  - {u.get('name', '<no name>'):25s} {u.get('phone'):15s} id={u.get('id')}")

    confirm = input("\nProceed with DELETE? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted, no changes made.")
        return

    print()
    for u in targets:
        status, body = delete_user(token, str(u["id"]))
        marker = "✓" if status in (200, 204) else "✗"
        print(f"  {marker} {u.get('name', '?'):25s} HTTP {status} {body if status >= 300 else ''}")

    print("\nDone. Refresh the admin panel — these rows should disappear.")
    print("The Flutter app leaderboard will fall back to the new empty state on next /leaderboard fetch.")


if __name__ == "__main__":
    main()
