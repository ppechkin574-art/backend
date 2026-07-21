"""Weekly sprint — allowlist, live standings, week close-out, tie splits.

CRM #19 ("Логика всего блока — Еженедельный спринт"), building on #6
(weekly points reset) and #7 (threshold winner lock-in).

How a week is decided, in one place:

    Monday 00:00 Almaty ──────────────────────────► Sunday 23:59
              │                                            │
              │  someone on the allowlist crosses          │
              │  `sprint_target_points` (if configured)    │
              ▼                                            ▼
        threshold win, week closes early          close_week_if_due()
        (`try_lock_sprint_winner`)                        │
                                        ┌─────────────────┴────────────┐
                                 single top scorer            2+ tied at top
                                        │                             │
                                    `closest`                   `tie_pending`
                                                                      │
                                                        admin resolve_tie()
                                                                      │
                                                                `tie_split`

Everything here reads points from `points_audit_log`, never from
`user_points.total_points` — the all-time "Кубок" rating must keep
accumulating untouched while the sprint restarts every Monday.

Display names and avatars are NOT resolved here. Like the rest of the
leaderboard, that lookup (user_display snapshot → Keycloak fallback →
presigned MinIO avatar) lives at the route layer, and these methods
return raw user ids for the route to enrich.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from leaderboard_points.models import (
    RESOLUTION_CLOSEST,
    RESOLUTION_TIE_PENDING,
    SprintParticipant,
)
from leaderboard_points.repository import LeaderboardPointsRepository
from leaderboard_points.service import (
    current_day_start_almaty,
    current_week_bounds_almaty,
)

logger = logging.getLogger(__name__)

# Kazakhstani mobile numbers: +7 7XX XXX XX XX.
_KZ_PHONE_RE = re.compile(r"^\+7\d{10}$")


class InvalidPhoneNumber(ValueError):
    """Raised for input that cannot be normalized to +7XXXXXXXXXX."""


def normalize_phone(raw: str) -> str:
    """Canonical `+7XXXXXXXXXX`. Accepts the shapes admins actually paste —
    `8 700 123 45 67`, `+7 (700) 123-45-67`, `7001234567` — because the
    allowlist is keyed on this string and a formatting difference would
    silently create a second, non-matching entry for the same person."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        digits = "+" + digits
    elif len(digits) == 10 and not digits.startswith("+"):
        digits = "+7" + digits
    if not _KZ_PHONE_RE.match(digits):
        raise InvalidPhoneNumber(f"expected +7XXXXXXXXXX, got {raw!r}")
    return digits


class SprintService:
    def __init__(self, repo: LeaderboardPointsRepository):
        self.repo = repo

    # ---------- participants ----------

    def list_participants(self) -> list[SprintParticipant]:
        return self.repo.list_participants()

    def add_participant(
        self, phone_number: str, user_id: UUID | None, added_by_display: str
    ) -> tuple[SprintParticipant, bool]:
        """Returns `(participant, created)`. Adding an existing number is
        NOT an error: it re-returns the row with `created=False`, and
        backfills `user_id` if the caller now knows it. Admins add people
        as payments land and a double click must not 500 on them."""
        phone = normalize_phone(phone_number)
        existing = self.repo.get_participant_by_phone(phone)
        if existing is not None:
            if user_id is not None and existing.user_id is None:
                self.repo.set_participant_user_id(existing.id, user_id)
            return existing, False
        return self.repo.add_participant(phone, user_id, added_by_display), True

    def remove_participant(self, participant_id: int) -> bool:
        """Removing someone mid-week drops them from the standings, but any
        week they already WON stays in history — `sprint_winners` rows are
        never revoked."""
        return self.repo.delete_participant(participant_id)

    def backfill_user_id(self, participant_id: int, user_id: UUID) -> None:
        self.repo.set_participant_user_id(participant_id, user_id)

    # ---------- live standings ----------

    def _eligible_user_ids(self) -> list[UUID]:
        """Allowlisted users who have an account and are not hidden from
        the leaderboard."""
        from quiz.repositories.leaderboard_hidden import LeaderboardHiddenRepository

        hidden = set(LeaderboardHiddenRepository(self.repo.db).get_all())
        return [u for u in self.repo.participant_user_ids() if str(u) not in hidden]

    def standings(
        self, week_start_at: datetime, week_end_at: datetime
    ) -> list[tuple[UUID, int, datetime]]:
        """(user_id, points, last_scored_at), best first, for the given
        week window. Empty when nobody is allowlisted — which is exactly
        what an unconfigured sprint should look like."""
        return self.repo.weekly_points(
            week_start_at, week_end_at, self._eligible_user_ids()
        )

    def ranked_standings(
        self, now: datetime | None = None, limit: int = 100
    ) -> dict:
        """Ranked weekly standings for `GET /leaderboard/weekly/standings`.

        Returns raw rows the route enriches with names/avatars:
          {settings…, week bounds, participants_total, finished,
           entries: [(user_id, points, rank, delta)], ...}

        `delta` is today's movement: this row's live rank minus its rank in
        the most recent snapshot before today's 00:00 Almaty. Positive =
        moved up. None when there's no earlier snapshot (first day of the
        week), so the client shows no badge rather than a fake zero."""
        now = now or datetime.now(UTC)
        week_start_at, week_end_at = current_week_bounds_almaty(now)
        rows = self.repo.weekly_points(
            week_start_at, week_end_at, self._eligible_user_ids()
        )

        day_start = current_day_start_almaty(now)
        prev_ranks = self.repo.latest_snapshot_ranks(week_start_at, day_start)

        entries = []
        for i, (user_id, points, _) in enumerate(rows[:limit]):
            rank = i + 1
            prev = prev_ranks.get(user_id)
            delta = (prev - rank) if prev is not None else None
            entries.append((user_id, points, rank, delta))

        settings = self.repo.get_or_create_settings()
        winner_row = self.repo.get_current_sprint_winner_row(week_start_at)
        return {
            "title_ru": settings.sprint_title_ru,
            "title_kk": settings.sprint_title_kk,
            "prize_amount": settings.sprint_prize_amount,
            "access_url": settings.sprint_access_url,
            "week_start_at": week_start_at,
            "week_end_at": week_end_at,
            "participants_total": self.repo.count_participants(),
            "finished": winner_row is not None,
            # (user_id, points_at_win) of the early-win threshold winner, or
            # None. The route resolves the name/avatar like any other row.
            "winner": (winner_row[0], winner_row[1]) if winner_row else None,
            "entries": entries,
        }

    def is_participant(self, user_id: UUID) -> bool:
        return self.repo.is_participant(user_id)

    # ---------- sprint test: per-answer scoring ----------

    def score_answer(
        self,
        user_id: UUID,
        question_id: int,
        variant_ids: list[int],
        test_id: int | None = None,
    ) -> dict:
        """Award sprint points for one correct answer in the sprint test.

        Correctness is checked SERVER-SIDE against the question's variants —
        the client's chosen variant ids are compared to the stored correct
        set, never a client-sent "correct" flag, so the answer can't be
        faked. Each question is worth points once per week (guarded by the
        audit log), so replaying the same answer earns nothing the second
        time.

        Returns {correct, awarded, week_points}:
          - correct: whether the answer was right;
          - awarded: points actually added (0 if wrong, already scored, or
            feature disabled);
          - week_points: the user's running sprint total this week, so the
            client can update the live rank pill without a second request.

        Points go through the normal add_points funnel, so the threshold
        winner hook fires here too — a sprint test can win the week early."""
        now = datetime.now(UTC)
        week_start_at, week_end_at = current_week_bounds_almaty(now)

        per_answer = self.repo.get_or_create_settings().sprint_points_per_answer or 0
        correct_ids = self.repo.correct_variant_ids(question_id)
        correct = bool(correct_ids) and set(variant_ids) == correct_ids

        # Idempotency scope. With a test_id the key is (attempt, question) —
        # a fresh test scores the same question again ("платить каждый тест"),
        # while a re-tap inside the SAME test still can't double-credit. Without
        # one (legacy client) it falls back to per-week per-question.
        source_id = f"{test_id}:{question_id}" if test_id is not None else str(question_id)

        awarded = 0
        if (
            correct
            and per_answer > 0
            and not self.repo.sprint_answer_already_scored(
                user_id, week_start_at, source_id
            )
        ):
            from quiz.repositories.user_points import UserPointsRepository

            UserPointsRepository(self.repo.db).add_points(
                user_id,
                per_answer,
                source_type="sprint_answer",
                source_id=source_id,
                reason="Верный ответ в тесте спринта",
            )
            awarded = per_answer

        rows = self.repo.weekly_points(week_start_at, week_end_at, [user_id])
        week_points = rows[0][1] if rows else 0
        return {"correct": correct, "awarded": awarded, "week_points": week_points}

    def capture_rank_snapshot(self, now: datetime | None = None) -> dict:
        """Record today's rank snapshot (movement-badge baseline). Called on
        a schedule; only writes once per Almaty day thanks to the unique
        constraint, so an hourly poll is safe. Never raises — a failure here
        must not take down the lifespan task it shares."""
        now = now or datetime.now(UTC)
        try:
            week_start_at, week_end_at = current_week_bounds_almaty(now)
            day_start = current_day_start_almaty(now)
            if self.repo.snapshot_exists_for_day(week_start_at, day_start):
                return {"ran": False, "reason": "already_captured_today"}
            rows = self.repo.weekly_points(
                week_start_at, week_end_at, self._eligible_user_ids()
            )
            if not rows:
                return {"ran": False, "reason": "no_scorers"}
            ranks = [(user_id, i + 1) for i, (user_id, _, _) in enumerate(rows)]
            self.repo.save_rank_snapshot(week_start_at, day_start, ranks)
            return {"ran": True, "captured": len(ranks)}
        except Exception:
            logger.exception("capture_rank_snapshot failed (non-fatal)")
            return {"ran": False, "reason": "error"}

    # ---------- the mobile home card ----------

    def card_data(self, now: datetime | None = None) -> dict:
        """Raw payload for `GET /leaderboard/weekly`. `leader` is a raw
        `(user_id, points)` tuple or None; the route resolves the name and
        avatar. `finished` is True once this week has an early threshold
        winner — the card then shows that winner and "Спринт завершён"
        instead of a live leader and a countdown."""
        now = now or datetime.now(UTC)
        week_start_at, week_end_at = current_week_bounds_almaty(now)
        settings = self.repo.get_or_create_settings()

        winner_row = self.repo.get_current_sprint_winner_row(week_start_at)
        if winner_row is not None:
            leader = (winner_row[0], winner_row[1])
            finished = True
        else:
            rows = self.standings(week_start_at, week_end_at)
            leader = (rows[0][0], rows[0][1]) if rows else None
            finished = False

        return {
            "title_ru": settings.sprint_title_ru,
            "title_kk": settings.sprint_title_kk,
            "prize_amount": settings.sprint_prize_amount,
            "week_start_at": week_start_at,
            "week_end_at": week_end_at,
            "participants_total": self.repo.count_participants(),
            "leader": leader,
            "finished": finished,
        }

    # ---------- admin views ----------

    def current_week(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        week_start_at, week_end_at = current_week_bounds_almaty(now)
        settings = self.repo.get_or_create_settings()
        return {
            "week_start_at": week_start_at,
            "week_end_at": week_end_at,
            "target_points": settings.sprint_target_points,
            "prize_amount": settings.sprint_prize_amount,
            "participant_count": self.repo.count_participants(),
            "winners": self.repo.list_winners_for_week(week_start_at),
            "standings": self.standings(week_start_at, week_end_at),
        }

    def history(self, limit: int = 100):
        return self.repo.list_winners_history(limit=limit)

    def resolve_tie(self, week_start_at: datetime, resolved_by: str) -> tuple[int, int | None]:
        """Split the configured prize evenly between a week's tied winners.
        Returns `(winners_count, prize_share)`; `winners_count == 0` means
        the week has no pending tie and the caller should 404.

        Integer division floors the share — with 3 winners and 50 000 ₸ each
        gets 16 666 ₸ and 2 ₸ are not assigned to anyone. That is deliberate:
        the money is paid out by hand anyway, and quietly rounding one winner
        up would make the recorded shares disagree with the advertised prize."""
        pending = [
            w
            for w in self.repo.list_winners_for_week(week_start_at)
            if w.resolution_type == RESOLUTION_TIE_PENDING
        ]
        if not pending:
            return 0, None

        prize = self.repo.get_or_create_settings().sprint_prize_amount
        share = prize // len(pending) if prize else None
        affected = self.repo.resolve_tie(week_start_at, share, resolved_by)
        return affected, share

    # ---------- end-of-week job ----------

    def close_week_if_due(self, now: datetime | None = None) -> dict:
        """Resolve the week that has just ended. Called on a schedule (see
        `api.lifespan`), safe to run as often as you like: it only ever
        touches the PREVIOUS calendar week and does nothing once that week
        already has any winner row.

        Outcomes:
          * a `threshold` winner was locked in mid-week → nothing to do,
            the week is already decided;
          * exactly one top scorer → one `closest` row, whole prize;
          * several tied at the top → one `tie_pending` row each, no prize
            assigned until an admin splits it;
          * nobody scored / nobody allowlisted → no rows at all, the week
            simply had no winner.

        Never raises: a failure here must not take down the lifespan task
        that also drives the points auto-reset."""
        now = now or datetime.now(UTC)
        try:
            current_start, _ = current_week_bounds_almaty(now)
            week_start_at = current_start - timedelta(days=7)
            week_end_at = current_start

            if self.repo.week_has_winner(week_start_at):
                return {"ran": False, "reason": "already_resolved"}

            rows = self.standings(week_start_at, week_end_at)
            if not rows:
                return {"ran": False, "reason": "no_scorers"}

            top_points = rows[0][1]
            tied = [(uid, pts) for uid, pts, _ in rows if pts == top_points]

            if len(tied) == 1:
                prize = self.repo.get_or_create_settings().sprint_prize_amount
                self.repo.record_week_winners(
                    week_start_at, tied, RESOLUTION_CLOSEST, prize
                )
                logger.info(
                    "sprint week %s closed: single winner %s with %s points",
                    week_start_at.date(),
                    tied[0][0],
                    top_points,
                )
                return {"ran": True, "resolution": RESOLUTION_CLOSEST, "winners": 1}

            self.repo.record_week_winners(
                week_start_at, tied, RESOLUTION_TIE_PENDING, None
            )
            logger.info(
                "sprint week %s closed: %s-way tie at %s points, awaiting admin split",
                week_start_at.date(),
                len(tied),
                top_points,
            )
            return {
                "ran": True,
                "resolution": RESOLUTION_TIE_PENDING,
                "winners": len(tied),
            }
        except Exception:
            logger.exception("close_week_if_due failed (non-fatal)")
            return {"ran": False, "reason": "error"}
