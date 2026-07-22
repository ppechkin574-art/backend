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
    sprint_bounds,
)

logger = logging.getLogger(__name__)

# Kazakhstani mobile numbers: +7 7XX XXX XX XX.
_KZ_PHONE_RE = re.compile(r"^\+7\d{10}$")


class InvalidPhoneNumber(ValueError):
    """Raised for input that cannot be normalized to +7XXXXXXXXXX."""


class SprintWeekPendingClose(Exception):
    """A sprint week has ended and had scorers, but its winners aren't
    recorded yet. Removing a participant in this window could erase a pending
    prize (the week-close job reads live standings, which exclude a
    just-deleted participant), so deletion is refused until
    `close_week_if_due` resolves the week. The admin route maps it to a 409."""


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
        never revoked.

        Refuses (raises `SprintWeekPendingClose`) when a just-ended week still
        has its winners un-recorded and had scorers: deleting a participant
        then would drop them from the live standings the close job reads, so a
        deserved prize could silently vanish. The scheduled `close_week_if_due`
        clears this window within its run interval, after which deletion is
        allowed again."""
        if self._has_unresolved_ended_week(datetime.now(UTC)):
            raise SprintWeekPendingClose()
        return self.repo.delete_participant(participant_id)

    def _has_unresolved_ended_week(self, now: datetime) -> bool:
        """True while a sprint week has ended, had scorers, and hasn't had its
        winners recorded yet — the narrow window in which removing a
        participant could erase a pending prize (see `remove_participant`)."""
        settings = self.repo.get_or_create_settings()
        configured = isinstance(settings.sprint_start_at, datetime) and isinstance(
            settings.sprint_end_at, datetime
        )
        if configured:
            week_start_at, week_end_at = sprint_bounds(settings, now)
            if now < week_end_at:
                return False  # still running — no prize at stake yet
        else:
            # Legacy implicit-week sprint: the at-risk week is the PREVIOUS one
            # that rolled over at Monday 00:00 Almaty.
            current_start, _ = current_week_bounds_almaty(now)
            week_start_at = current_start - timedelta(days=7)
            week_end_at = current_start
        if self.repo.week_has_winner(week_start_at):
            return False  # already resolved — safe to delete
        return bool(self.standings(week_start_at, week_end_at))

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
        self, now: datetime | None = None, limit: int = 100, me_id: UUID | None = None
    ) -> dict:
        """Ranked weekly standings for `GET /leaderboard/weekly/standings`.

        Returns raw rows the route enriches with names/avatars:
          {settings…, week bounds, participants_total, finished,
           entries: [(user_id, points, rank, delta)], me, ...}

        `delta` is today's movement: this row's live rank minus its rank in
        the most recent snapshot before today's 00:00 Almaty. Positive =
        moved up. None when there's no earlier snapshot (first day of the
        week), so the client shows no badge rather than a fake zero.

        When `me_id` is given, the caller is pulled OUT of `entries` and
        returned separately as `me` (with the caller's true rank/delta) — the
        screen pins «вы» on its own, so leaving the row in the list too would
        show the caller twice. `me` is resolved from the FULL ranking, so a
        caller ranked below `limit` still gets their real position rather than
        vanishing."""
        now = now or datetime.now(UTC)
        settings = self.repo.get_or_create_settings()
        week_start_at, week_end_at = sprint_bounds(settings, now)
        eligible = self._eligible_user_ids()
        rows = self.repo.weekly_points(week_start_at, week_end_at, eligible)

        # Show ALL participants, not only scorers: someone who joined the
        # sprint but hasn't answered correctly yet appears at the bottom with
        # 0★ (access is join-based — a participant must be visible the moment
        # they join). weekly_points returns scorers best-first; append the
        # zero-score participants after them, keeping the allowlist order.
        scored_ids = {r[0] for r in rows}
        zeros = [(uid, 0, None) for uid in eligible if uid not in scored_ids]
        rows = list(rows) + zeros

        day_start = current_day_start_almaty(now)
        prev_ranks = self.repo.latest_snapshot_ranks(week_start_at, day_start)

        # Rank over the FULL field so ranks and the caller's own position are
        # correct even past `limit`; the caller is split out into `me` and the
        # public list is capped at `limit`.
        entries = []
        me_entry = None
        for i, (user_id, points, _) in enumerate(rows):
            rank = i + 1
            prev = prev_ranks.get(user_id)
            delta = (prev - rank) if prev is not None else None
            row = (user_id, points, rank, delta)
            if me_id is not None and user_id == me_id:
                me_entry = row  # caller pinned separately, never inside the list
                continue
            if len(entries) < limit:
                entries.append(row)

        winner, finished = self._resolve_finish(week_start_at, week_end_at, now)
        return {
            "title_ru": settings.sprint_title_ru,
            "title_kk": settings.sprint_title_kk,
            "prize_amount": settings.sprint_prize_amount,
            "access_url": settings.sprint_access_url,
            # Admin-set weekly goal (early-win threshold). Shown on the screen
            # as «Цель недели: N ★»; null → no goal configured, nothing shown.
            "target_points": settings.sprint_target_points,
            "week_start_at": week_start_at,
            "week_end_at": week_end_at,
            "participants_total": self.repo.count_participants(),
            # finished = won early OR the period has ended. `winner` is
            # (user_id, points) only once finished; live it's null (the top of
            # `entries` is the current leader). The route resolves the name.
            "finished": finished,
            "winner": winner if finished else None,
            "entries": entries,
            "me": me_entry,
        }

    def is_participant(self, user_id: UUID) -> bool:
        # Admin "open to all" rubilnik: when on, the sprint is free for
        # everyone and the allowlist is bypassed (rows kept for later).
        if self.repo.get_or_create_settings().sprint_open_to_all:
            return True
        return self.repo.is_participant(user_id)

    def join(self, user_id: UUID, phone: str | None = None) -> None:
        """Self-enroll the current user into the sprint (join-based access —
        the «Участвовать» button). Idempotent: already a participant → no-op.

        If the admin granted this phone entry in advance (user_id NULL), link
        it to the account instead of creating a duplicate row — that is the
        same backfill the phone would get on first score, done eagerly here so
        the person joins their own pre-granted slot."""
        if self.repo.is_participant(user_id):
            return
        if phone:
            existing = self.repo.get_participant_by_phone(phone)
            if existing is not None and existing.user_id is None:
                self.repo.set_participant_user_id(existing.id, user_id)
                return
        # phone_number is NOT NULL, UNIQUE, varchar(20). Self-joiners may have
        # no phone (email/OAuth), so fall back to a 20-char id derived from the
        # user_id — unique per user, never collides with a real "+7…" phone.
        self.repo.add_participant(
            phone_number=(phone or str(user_id).replace("-", ""))[:20],
            user_id=user_id,
            added_by_display="self",
        )

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
        faked. Each question is worth points ONCE PER WEEK per user (the week
        is baked into the idempotency key and backed by a partial unique
        index), so re-answering the same question — even in a brand-new test —
        earns nothing more until the week rolls over.

        Returns {correct, awarded, week_points, finished}:
          - correct: whether the answer was right;
          - awarded: points actually added (0 if wrong, already scored this
            week, not a participant, feature disabled, or the sprint is over);
          - week_points: the user's running sprint total this week, so the
            client can update the live rank pill without a second request;
          - finished: the sprint is already decided (won early or the period
            ended) — the client should stop the test; no more points are given.

        The threshold winner hook fires here (`check_and_lock_sprint_winner`),
        so a sprint test can win the week early — and once it does, the sprint
        ends and this method stops awarding, freezing the final standings."""
        now = datetime.now(UTC)
        settings = self.repo.get_or_create_settings()
        week_start_at, week_end_at = sprint_bounds(settings, now)

        per_answer = settings.sprint_points_per_answer or 0
        correct_ids = self.repo.correct_variant_ids(question_id)
        correct = bool(correct_ids) and set(variant_ids) == correct_ids

        def _week_points() -> int:
            rows = self.repo.weekly_points(week_start_at, week_end_at, [user_id])
            return rows[0][1] if rows else 0

        # The sprint ends the moment it is won early (a threshold winner is
        # locked) or the period is over: from then on the standings are frozen
        # and NOBODY can be awarded more, so the winner can never be overtaken.
        # We still report `correct` for UI feedback, but award nothing and flag
        # `finished` so the client closes the test.
        won = self.repo.get_current_sprint_winner_row(week_start_at) is not None
        if won or now >= week_end_at:
            return {
                "correct": correct,
                "awarded": 0,
                "week_points": _week_points(),
                "finished": True,
            }

        # Participation gate (+ auto-enroll). Only people entered in the sprint
        # earn points. When the sprint is open to all, enrol the caller on their
        # first answer so they appear in the standings and the participant
        # count; otherwise a non-participant who reaches this endpoint earns
        # nothing (the paid-entry allowlist is the gate).
        if settings.sprint_open_to_all:
            self.join(user_id)  # idempotent
        elif not self.repo.is_participant(user_id):
            return {
                "correct": correct,
                "awarded": 0,
                "week_points": _week_points(),
                "finished": False,
            }

        # Idempotency scope: one credit per (user, question, week). The week is
        # baked into source_id, so the same question scores again next week but
        # never twice in the same week — whatever the client sends as test_id. A
        # partial unique index on (user_id, source_id) WHERE
        # source_type='sprint_answer' enforces this at the DB level, so racing
        # duplicate submits can't double-credit (record_sprint_answer_points
        # does ON CONFLICT DO NOTHING and returns False for the loser).
        source_id = f"{week_start_at.date().isoformat()}:{question_id}"

        awarded = 0
        # Separate currency: writes the audit row WITHOUT touching total_points,
        # so sprint play doesn't feed the global «Кубок». record_...  returns
        # False on conflict (already scored this week) or when points are frozen.
        if (
            correct
            and per_answer > 0
            and self.repo.record_sprint_answer_points(user_id, per_answer, source_id)
        ):
            awarded = per_answer

        week_points = _week_points()

        # Threshold early-win. Sprint points no longer flow through add_points'
        # shared hook, so the winner check runs here. Reuses the same gates
        # (target / participant / hidden / partial-unique lock).
        if awarded > 0:
            from leaderboard_points.service import LeaderboardPointsService

            LeaderboardPointsService(self.repo).check_and_lock_sprint_winner(
                user_id, week_points
            )

        return {
            "correct": correct,
            "awarded": awarded,
            "week_points": week_points,
            "finished": False,
        }

    def capture_rank_snapshot(self, now: datetime | None = None) -> dict:
        """Record today's rank snapshot (movement-badge baseline). Called on
        a schedule; only writes once per Almaty day thanks to the unique
        constraint, so an hourly poll is safe. Never raises — a failure here
        must not take down the lifespan task it shares."""
        now = now or datetime.now(UTC)
        try:
            settings = self.repo.get_or_create_settings()
            week_start_at, week_end_at = sprint_bounds(settings, now)
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
        settings = self.repo.get_or_create_settings()
        week_start_at, week_end_at = sprint_bounds(settings, now)

        leader, finished = self._resolve_finish(week_start_at, week_end_at, now)

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

    def _resolve_finish(
        self, start: datetime, end: datetime, now: datetime
    ) -> tuple[tuple | None, bool]:
        """`(leader_or_winner, finished)` for the card/screen.

        finished is True when the sprint was won early (a `threshold` row) OR
        the period has ended (`now >= end`). The tuple is `(user_id, points)`:
        the locked winner when there is one, otherwise the current top scorer —
        which, once the period is over, is effectively the `closest` winner even
        before the scheduled close job records it. `None` when nobody scored."""
        threshold = self.repo.get_current_sprint_winner_row(start)
        if threshold is not None:
            return (threshold[0], threshold[1]), True
        over = now >= end
        recorded = self.repo.list_winners_for_week(start) if over else []
        if recorded:
            w = recorded[0]
            return (w.user_id, w.points_at_win), True
        rows = self.standings(start, end)
        leader = (rows[0][0], rows[0][1]) if rows else None
        return leader, over

    # ---------- admin views ----------

    def current_week(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        settings = self.repo.get_or_create_settings()
        week_start_at, week_end_at = sprint_bounds(settings, now)
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
            settings = self.repo.get_or_create_settings()
            configured = isinstance(settings.sprint_start_at, datetime) and isinstance(
                settings.sprint_end_at, datetime
            )
            if configured:
                # Date-based sprint: resolve it once its period is over. While
                # it's still running there is nothing to close.
                week_start_at, week_end_at = sprint_bounds(settings, now)
                if now < week_end_at:
                    return {"ran": False, "reason": "not_over"}
            else:
                # Legacy implicit-week sprint: resolve the PREVIOUS week (the
                # one that just rolled over at Monday 00:00 Almaty).
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
                prize = settings.sprint_prize_amount
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
