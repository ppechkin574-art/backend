"""Seed test events via the admin API.

Creates a temporary Keycloak admin user, seeds events via the API, then deletes the temp user.
Run after Railway deploys the events module (i.e. GET /events returns [] not 404).
"""

import sys
import requests
from datetime import datetime, timedelta, timezone

BACKEND = "https://backend-production-f2a1.up.railway.app"
KC_URL  = "https://keycloak-production-0a0c.up.railway.app"
KC_ADMIN_PSW = "gRv6grqO0OcQCnCCXRD4d2B90ZMsNquf"
REALM = "lumi"
TEMP_EMAIL = "seed_temp_admin@aima.kz"
TEMP_PASS  = "TempSeed2026!xZ"

now = datetime.now(timezone.utc)

EVENTS = [
    {
        "type": "banner",
        "badge_text": "Турнир",
        "title": "Большой турнир AIMA",
        "prize_text": "5 000 000 ₸",
        "subtitle": "Реши 200 вопросов\nи войди в топ-10",
        "secondary_text": None,
        "deadline": (now + timedelta(days=30)).isoformat(),
        "button_text": "Участвовать",
        "bg_color": "#5B2EC4",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 1,
        "is_active": True,
    },
    {
        "type": "banner",
        "badge_text": "Еженедельный",
        "title": "Конкурс недели",
        "prize_text": "100 000 ₸",
        "subtitle": "Лучший результат\nпо математике за неделю",
        "secondary_text": None,
        "deadline": (now + timedelta(days=5)).isoformat(),
        "button_text": "Начать",
        "bg_color": "#3D1A8E",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 2,
        "is_active": True,
    },
    {
        "type": "card",
        "badge_text": "Чемпионат",
        "title": "Весенний чемпионат",
        "prize_text": "500 000 ₸",
        "subtitle": None,
        "secondary_text": "12 340 участников",
        "deadline": None,
        "button_text": None,
        "bg_color": "#5B2EC4",
        "progress_current": 12340,
        "progress_max": 50000,
        "sort_order": 3,
        "is_active": True,
    },
    {
        "type": "card",
        "badge_text": "Математика",
        "title": "Турнир по математике",
        "prize_text": "250 000 ₸",
        "subtitle": None,
        "secondary_text": "Открытое участие",
        "deadline": (now + timedelta(days=12)).isoformat(),
        "button_text": None,
        "bg_color": "#FFFFFF",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 4,
        "is_active": True,
    },
    {
        "type": "card",
        "badge_text": "Кубок",
        "title": "Кубок AIMA",
        "prize_text": "1 000 000 ₸",
        "subtitle": None,
        "secondary_text": "Только для PRO-участников",
        "deadline": (now + timedelta(days=21)).isoformat(),
        "button_text": None,
        "bg_color": "#1A0A4E",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 5,
        "is_active": True,
    },
]


def get_kc_admin_token():
    r = requests.post(
        f"{KC_URL}/realms/master/protocol/openid-connect/token",
        data={"username": "admin", "password": KC_ADMIN_PSW,
              "grant_type": "password", "client_id": "admin-cli"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_temp_admin(kc_token):
    headers = {"Authorization": f"Bearer {kc_token}", "Content-Type": "application/json"}

    r = requests.post(
        f"{KC_URL}/admin/realms/{REALM}/users",
        json={"username": TEMP_EMAIL, "email": TEMP_EMAIL, "enabled": True,
              "emailVerified": True,
              "credentials": [{"type": "password", "value": TEMP_PASS, "temporary": False}]},
        headers=headers, timeout=15,
    )
    if r.status_code == 409:
        print("  Temp user exists, reusing.")
    elif r.status_code == 201:
        print("  Created temp user.")
    else:
        r.raise_for_status()

    r2 = requests.get(
        f"{KC_URL}/admin/realms/{REALM}/users?email={TEMP_EMAIL}",
        headers=headers, timeout=15,
    )
    r2.raise_for_status()
    users = r2.json()
    user_id = users[0]["id"]
    print(f"  User ID: {user_id}")
    return user_id


def assign_admin_role(kc_token, user_id):
    headers = {"Authorization": f"Bearer {kc_token}", "Content-Type": "application/json"}
    r = requests.get(f"{KC_URL}/admin/realms/{REALM}/roles/admin",
                     headers=headers, timeout=15)
    r.raise_for_status()
    role = r.json()
    r2 = requests.post(
        f"{KC_URL}/admin/realms/{REALM}/users/{user_id}/role-mappings/realm",
        json=[role], headers=headers, timeout=15,
    )
    r2.raise_for_status()
    print(f"  Assigned role 'admin'.")


def get_backend_token():
    r = requests.post(f"{BACKEND}/auth/login",
                      json={"login": TEMP_EMAIL, "password": TEMP_PASS},
                      timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Backend login failed {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def delete_temp_user(kc_token, user_id):
    r = requests.delete(
        f"{KC_URL}/admin/realms/{REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {kc_token}"},
        timeout=15,
    )
    if r.status_code in (200, 204):
        print("  Temp user deleted.")
    else:
        print(f"  Warning: delete failed {r.status_code}: {r.text[:100]}")


def seed_events(access_token):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    for ev in EVENTS:
        r = requests.post(f"{BACKEND}/admin/events", json=ev, headers=headers, timeout=15)
        if r.status_code == 201:
            print(f"  ✓ [{ev['type']:6s}] {ev['title']}")
        else:
            print(f"  ✗ {ev['title']}: {r.status_code} {r.text[:200]}")


def main():
    print("1. Getting Keycloak admin token...")
    kc_token = get_kc_admin_token()
    print("   OK")

    print("2. Creating temporary admin user in lumi realm...")
    user_id = create_temp_admin(kc_token)

    print("3. Assigning admin role...")
    assign_admin_role(kc_token, user_id)

    print("4. Logging into backend...")
    access_token = get_backend_token()
    print("   OK")

    print("5. Seeding events...")
    seed_events(access_token)

    print("6. Cleaning up temp user...")
    delete_temp_user(kc_token, user_id)

    print("\n✓ Done — check the app!")


if __name__ == "__main__":
    main()
