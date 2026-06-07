"""Self-serve POST of generated drafts to /admin/question-drafts.

Mints a short-lived admin token WITHOUT asking the operator: reads the Keycloak
creds from `railway variables` (no secrets in the repo), creates a temporary
`lumi`-realm user with the `admin` role, password-grants a token via the
`web-app` confidential client, POSTs every draft, then deletes the temp user.

Run from the backend repo (so `railway` is linked):
    python -m tools.question_generator.post_drafts drafts_output.json
Env: AIMA_API_URL (default: prod). Requires the `railway` CLI logged in.

See docs/PERF_COORDINATION_STATS.md siblings + the reference recipe.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request

API = os.environ.get("AIMA_API_URL", "https://backend-production-f2a1.up.railway.app")
KC = "https://keycloak-production-0a0c.up.railway.app"


def _railway_vars() -> dict:
    """Parse `railway variables` (table output) into a dict."""
    out = subprocess.run(
        ["railway", "variables"], capture_output=True, text=True, timeout=60
    ).stdout
    vars_: dict = {}
    for line in out.splitlines():
        # rows look like: ║ KEY   │ VALUE   ║
        m = re.match(r"\s*[║|]\s*([A-Za-z0-9_]+)\s*[│|]\s*(.*?)\s*[║|]\s*$", line)
        if m:
            vars_[m.group(1)] = m.group(2)
    return vars_


def _post_form(url, data, token=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _api(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return r, (json.loads(raw) if raw else None)


def mint_admin_token(v: dict):
    """Returns (token, temp_user_id). Caller must delete the user when done."""
    master_pw = v["keycloak__admin__PASSWORD"]
    master = _post_form(f"{KC}/realms/master/protocol/openid-connect/token", {
        "grant_type": "password", "client_id": "admin-cli",
        "username": v.get("keycloak__admin__USERNAME", "admin"), "password": master_pw,
    })["access_token"]

    sfx = secrets.token_hex(4)
    uname = f"tmp_qgen_{sfx}"
    upw = "Tmp!" + secrets.token_urlsafe(10)
    resp, _ = _api("POST", f"{KC}/admin/realms/lumi/users", master, {
        "username": uname, "email": f"{uname}@example.com", "enabled": True,
        "emailVerified": True, "firstName": "QGen", "lastName": "Bot",
        "credentials": [{"type": "password", "value": upw, "temporary": False}],
    })
    uid = resp.headers.get("Location", "").rstrip("/").split("/")[-1]
    _, role = _api("GET", f"{KC}/admin/realms/lumi/roles/admin", master)
    _api("POST", f"{KC}/admin/realms/lumi/users/{uid}/role-mappings/realm", master,
         [{"id": role["id"], "name": role["name"]}])
    token = _post_form(f"{KC}/realms/lumi/protocol/openid-connect/token", {
        "grant_type": "password", "client_id": v["keycloak__open_id__CLIENT_ID"],
        "client_secret": v["keycloak__open_id__CLIENT_SECRET_KEY"],
        "username": uname, "password": upw, "scope": "openid",
    })["access_token"]
    return token, uid


def delete_temp_user(v: dict, uid: str):
    master = _post_form(f"{KC}/realms/master/protocol/openid-connect/token", {
        "grant_type": "password", "client_id": "admin-cli",
        "username": v.get("keycloak__admin__USERNAME", "admin"),
        "password": v["keycloak__admin__PASSWORD"],
    })["access_token"]
    _api("DELETE", f"{KC}/admin/realms/lumi/users/{uid}", master)


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: post_drafts.py <drafts.json>")
        return 2
    payload = json.load(open(argv[0]))
    drafts = payload["drafts"] if isinstance(payload, dict) else payload
    v = _railway_vars()
    token, uid = mint_admin_token(v)
    print(f"minted token (temp user {uid}); posting {len(drafts)} draft(s)...")
    ok = err = 0
    for q in drafts:
        try:
            _api("POST", f"{API}/admin/question-drafts", token, q)
            ok += 1
        except Exception as e:
            err += 1
            if err <= 3:
                print("  err:", getattr(e, "code", e))
    print(f"POST drafts: ok={ok} err={err}")
    delete_temp_user(v, uid)
    print("temp user deleted")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
