"""record_notification — atomic dedup for Apple S2S notifications.

First sight of a notificationUUID → insert succeeds → returns True (process it).
Duplicate → the UNIQUE pk insert raises IntegrityError → returns False (skip).
Any other DB error → fail open (True) so a renewal is never silently dropped.
"""

from sqlalchemy.exc import IntegrityError

from payments.apple_notification import record_notification


class _Sess:
    """Fake session that mimics a UNIQUE constraint on notification_uuid."""

    def __init__(self, seen=None, blow_up=False):
        self.seen = set(seen or [])
        self.blow_up = blow_up
        self.committed = 0
        self.rolled = 0
        self._pending = None

    def add(self, row):
        if self.blow_up:
            raise RuntimeError("unexpected db error")
        if row.notification_uuid in self.seen:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        self._pending = row

    def commit(self):
        self.seen.add(self._pending.notification_uuid)
        self.committed += 1

    def rollback(self):
        self.rolled += 1


def test_first_sight_records_and_returns_true():
    s = _Sess()
    assert record_notification(s, "uuid-1", "DID_RENEW", "raw") is True
    assert "uuid-1" in s.seen
    assert s.committed == 1


def test_duplicate_returns_false_and_rolls_back():
    s = _Sess(seen=["uuid-1"])
    assert record_notification(s, "uuid-1", "DID_RENEW", "raw") is False
    assert s.rolled == 1
    assert s.committed == 0


def test_unexpected_error_fails_open_true():
    # A non-Integrity DB hiccup must not drop the event — process it (downstream
    # is idempotent), better a rare double-process than a lost renewal.
    s = _Sess(blow_up=True)
    assert record_notification(s, "uuid-2", "DID_RENEW", "raw") is True
    assert s.rolled == 1
