"""Seed random test events for Главная screen.

Run after the events table migration is applied:
  DATABASE_URL="postgresql://..." python3 scripts/seed_events.py

Or set DATABASE_URL env var in advance.
"""

import os
import sys
import psycopg2
from datetime import datetime, timedelta, timezone

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:aFsRkzGZFajptqkLkMGystWMInIPgiqn@switchyard.proxy.rlwy.net:47781/railway",
)

now = datetime.now(timezone.utc)

EVENTS = [
    # ── Banners (carousel) ───────────────────────────────────────────────
    {
        "type": "banner",
        "badge_text": "Турнир",
        "title": "Большой турнир AIMA",
        "prize_text": "5 000 000 ₸",
        "subtitle": "Реши 200 вопросов\nи войди в топ-10",
        "secondary_text": None,
        "deadline": now + timedelta(days=30),
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
        "deadline": now + timedelta(days=5),
        "button_text": "Начать",
        "bg_color": "#3D1A8E",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 2,
        "is_active": True,
    },
    # ── Cards (events grid) ──────────────────────────────────────────────
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
        "deadline": now + timedelta(days=12),
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
        "secondary_text": "Только PRO-участники",
        "deadline": now + timedelta(days=21),
        "button_text": None,
        "bg_color": "#1A0A4E",
        "progress_current": None,
        "progress_max": None,
        "sort_order": 5,
        "is_active": True,
    },
]

INSERT = """
INSERT INTO events (
  type, badge_text, title, prize_text, subtitle, secondary_text,
  deadline, button_text, bg_color, progress_current, progress_max,
  sort_order, is_active
) VALUES (
  %(type)s, %(badge_text)s, %(title)s, %(prize_text)s, %(subtitle)s, %(secondary_text)s,
  %(deadline)s, %(button_text)s, %(bg_color)s, %(progress_current)s, %(progress_max)s,
  %(sort_order)s, %(is_active)s
)
"""

def main():
    print(f"Connecting to DB…")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    except Exception:
        conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Clear existing seed data
    cur.execute("DELETE FROM events")
    print("Cleared existing events.")

    for ev in EVENTS:
        cur.execute(INSERT, ev)
        print(f"  ✓ {ev['type']:6s}  {ev['title']}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone — seeded {len(EVENTS)} events.")

if __name__ == "__main__":
    main()
