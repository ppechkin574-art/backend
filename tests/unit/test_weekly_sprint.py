"""CRM #19 — weekly sprint: allowlist, weekly scoring, week close, ties.

Covers the decisions that are easy to regress and expensive to notice:

- `normalize_phone` — the allowlist is keyed on this string, so every
  shape an admin might paste must collapse to one canonical form.
- `current_week_bounds_almaty` — half-open [Mon 00:00, next Mon 00:00)
  in Almaty, which is what "this week" means for every other component.
- `SprintService.close_week_if_due` — the four end-of-week outcomes:
  already resolved / nobody scored / single winner / tie. A tie must
  NOT be auto-split; that is an admin decision.
- `SprintService.resolve_tie` — even split, floored, and a 0 result for
  a week with no pending tie (the route turns that into a 404).
- `SprintService.card_data` — the four card states the mobile app
  renders, in particular that a locked threshold winner flips the card
  to `finished` and replaces the live leader.
- `LeaderboardPointsService.check_and_lock_sprint_winner` — the gate
  that non-participants can earn points but never win, and that the
  threshold is compared against WEEKLY points, not the all-time total.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# Eager imports so SQLAlchemy mappers resolve relationships.
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from leaderboard_points.models import (
    RESOLUTION_CLOSEST,
    RESOLUTION_THRESHOLD,
    RESOLUTION_TIE_PENDING,
)
from leaderboard_points.service import current_week_bounds_almaty
from leaderboard_points.sprint import (
    InvalidPhoneNumber,
    SprintService,
    normalize_phone,
)


# --------------------------------------------------------------------
# phone normalization
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "+77001234567",
        "87001234567",
        "8 700 123 45 67",
        "+7 (700) 123-45-67",
        "77001234567",
        "7001234567",
    ],
)
def test_normalize_phone_collapses_every_admin_input_shape(raw):
    assert normalize_phone(raw) == "+77001234567"


@pytest.mark.parametrize("raw", ["", "12345", "+1 202 555 0134", "abc", None])
def test_normalize_phone_rejects_non_kz_numbers(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


# --------------------------------------------------------------------
# week bounds
# --------------------------------------------------------------------


def test_week_bounds_are_half_open_and_anchored_to_almaty_monday():
    # Wednesday 2026-07-22, 10:00 UTC == 15:00 Almaty.
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    start, end = current_week_bounds_almaty(now)

    # Monday 2026-07-20 00:00 Almaty == Sunday 2026-07-19 19:00 UTC.
    assert start == datetime(2026, 7, 19, 19, 0, tzinfo=UTC)
    assert end - start == timedelta(days=7)
    assert start <= now < end


def test_week_bounds_do_not_overlap_between_consecutive_weeks():
    """The end bound is exclusive and equals the next week's start, so a
    point scored on the boundary belongs to exactly one week."""
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    _, end = current_week_bounds_almaty(now)
    next_start, _ = current_week_bounds_almaty(end)
    assert next_start == end


# --------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------


def _service(*, standings=None, participants=None, has_winner=False, prize=None):
    """SprintService over a mocked repository. `standings` is the list of
    (user_id, points, last_scored_at) `weekly_points` would return."""
    repo = MagicMock()
    repo.weekly_points.return_value = standings or []
    repo.participant_user_ids.return_value = participants or []
    repo.count_participants.return_value = len(participants or [])
    repo.week_has_winner.return_value = has_winner
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_prize_amount=prize,
        sprint_target_points=None,
        sprint_title_ru="Еженедельный спринт",
        sprint_title_kk="Апталық спринт",
    )
    repo.get_current_sprint_winner_row.return_value = None
    repo.record_week_winners.return_value = 1
    repo.list_winners_for_week.return_value = []

    service = SprintService(repo)
    # _eligible_user_ids consults the leaderboard hide-list through the
    # session; stub it out — hide-list behaviour is covered by CRM #7 tests.
    service._eligible_user_ids = lambda: participants or []
    return service, repo


# --------------------------------------------------------------------
# week close
# --------------------------------------------------------------------


def test_close_week_does_nothing_when_week_already_resolved():
    service, repo = _service(has_winner=True)
    result = service.close_week_if_due(datetime(2026, 7, 22, 10, 0, tzinfo=UTC))
    assert result == {"ran": False, "reason": "already_resolved"}
    repo.record_week_winners.assert_not_called()


def test_close_week_does_nothing_when_nobody_scored():
    """An empty allowlist and an allowlist where nobody played look the
    same here — neither produces a winner, and neither is an error."""
    service, repo = _service(standings=[], participants=[uuid4()])
    result = service.close_week_if_due(datetime(2026, 7, 22, 10, 0, tzinfo=UTC))
    assert result == {"ran": False, "reason": "no_scorers"}
    repo.record_week_winners.assert_not_called()


def test_close_week_records_single_winner_with_whole_prize():
    winner, runner_up = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _service(
        standings=[(winner, 500, now), (runner_up, 300, now)],
        participants=[winner, runner_up],
        prize=50_000,
    )

    result = service.close_week_if_due(now)

    assert result == {"ran": True, "resolution": RESOLUTION_CLOSEST, "winners": 1}
    _, kwargs_entries, resolution, share = repo.record_week_winners.call_args[0]
    assert kwargs_entries == [(winner, 500)]
    assert resolution == RESOLUTION_CLOSEST
    assert share == 50_000


def test_sprint_bounds_uses_configured_dates_over_the_week():
    from leaderboard_points.service import sprint_bounds

    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    settings = MagicMock(sprint_start_at=start, sprint_end_at=end)
    assert sprint_bounds(settings, datetime(2026, 8, 2, tzinfo=UTC)) == (start, end)


def test_sprint_bounds_falls_back_to_current_week_when_unset():
    from leaderboard_points.service import sprint_bounds

    settings = MagicMock(sprint_start_at=None, sprint_end_at=None)
    now = datetime(2026, 7, 22, 10, tzinfo=UTC)
    assert sprint_bounds(settings, now) == current_week_bounds_almaty(now)


def test_close_is_a_noop_while_a_configured_sprint_is_still_running():
    now = datetime(2026, 8, 2, 10, tzinfo=UTC)  # inside [Aug 1, Aug 5)
    service, repo = _service(participants=[uuid4()])
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_start_at=datetime(2026, 8, 1, tzinfo=UTC),
        sprint_end_at=datetime(2026, 8, 5, tzinfo=UTC),
        sprint_prize_amount=50_000,
    )
    result = service.close_week_if_due(now)
    assert result["ran"] is False and result["reason"] == "not_over"
    repo.record_week_winners.assert_not_called()


def test_close_records_winner_once_the_configured_sprint_has_ended():
    winner = uuid4()
    now = datetime(2026, 8, 6, 10, tzinfo=UTC)  # after Aug 5 end
    service, repo = _service(
        standings=[(winner, 120, now)], participants=[winner], prize=50_000
    )
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_start_at=datetime(2026, 8, 1, tzinfo=UTC),
        sprint_end_at=datetime(2026, 8, 5, tzinfo=UTC),
        sprint_prize_amount=50_000,
    )
    repo.week_has_winner.return_value = False
    result = service.close_week_if_due(now)
    assert result["ran"] is True
    entries = repo.record_week_winners.call_args[0][1]
    assert entries == [(winner, 120)]


def test_close_week_leaves_a_tie_for_the_admin_instead_of_splitting_it():
    """Two users on the same score must NOT be resolved automatically —
    the runner-up ordering inside `weekly_points` is display-only."""
    a, b, c = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _service(
        standings=[(a, 500, now), (b, 500, now), (c, 100, now)],
        participants=[a, b, c],
        prize=50_000,
    )

    result = service.close_week_if_due(now)

    assert result == {"ran": True, "resolution": RESOLUTION_TIE_PENDING, "winners": 2}
    _, entries, resolution, share = repo.record_week_winners.call_args[0]
    assert sorted(e[0] for e in entries) == sorted([a, b])
    assert resolution == RESOLUTION_TIE_PENDING
    assert share is None, "no prize is assigned until the admin splits it"


def test_close_week_resolves_the_previous_week_not_the_current_one():
    winner = uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _service(
        standings=[(winner, 500, now)], participants=[winner], prize=1000
    )

    service.close_week_if_due(now)

    current_start, _ = current_week_bounds_almaty(now)
    recorded_week = repo.record_week_winners.call_args[0][0]
    assert recorded_week == current_start - timedelta(days=7)


def test_close_week_never_raises():
    service, repo = _service()
    repo.week_has_winner.side_effect = RuntimeError("db is down")
    assert service.close_week_if_due()["ran"] is False


# --------------------------------------------------------------------
# tie resolution
# --------------------------------------------------------------------


def test_resolve_tie_splits_the_prize_evenly_and_floors_the_remainder():
    """3 winners × 50 000 ₸ → 16 666 each. The leftover 2 ₸ stay
    unassigned rather than quietly inflating one winner's share."""
    service, repo = _service(prize=50_000)
    repo.list_winners_for_week.return_value = [
        MagicMock(resolution_type=RESOLUTION_TIE_PENDING) for _ in range(3)
    ]
    repo.resolve_tie.return_value = 3

    count, share = service.resolve_tie(datetime.now(UTC), "admin@aima.kz")

    assert (count, share) == (3, 16_666)


def test_resolve_tie_returns_zero_when_week_has_no_pending_tie():
    service, repo = _service(prize=50_000)
    repo.list_winners_for_week.return_value = [
        MagicMock(resolution_type=RESOLUTION_CLOSEST)
    ]
    assert service.resolve_tie(datetime.now(UTC), "admin@aima.kz") == (0, None)
    repo.resolve_tie.assert_not_called()


def test_resolve_tie_handles_a_week_with_no_prize_configured():
    service, repo = _service(prize=None)
    repo.list_winners_for_week.return_value = [
        MagicMock(resolution_type=RESOLUTION_TIE_PENDING) for _ in range(2)
    ]
    repo.resolve_tie.return_value = 2
    count, share = service.resolve_tie(datetime.now(UTC), "admin@aima.kz")
    assert (count, share) == (2, None)


# --------------------------------------------------------------------
# the mobile card
# --------------------------------------------------------------------


def test_card_shows_no_leader_when_allowlist_is_empty():
    """Empty allowlist == nobody competes. The card still renders its
    title/prize/countdown, just without the right-hand column."""
    service, _ = _service(participants=[], standings=[])
    data = service.card_data(datetime(2026, 7, 22, 10, 0, tzinfo=UTC))
    assert data["leader"] is None
    assert data["finished"] is False
    assert data["participants_total"] == 0


def test_card_shows_current_leader_mid_week():
    leader, other = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, _ = _service(
        standings=[(leader, 480, now), (other, 120, now)],
        participants=[leader, other],
        prize=50_000,
    )
    data = service.card_data(now)
    assert data["leader"] == (leader, 480)
    assert data["finished"] is False
    assert data["participants_total"] == 2
    assert data["prize_amount"] == 50_000


def test_card_flips_to_finished_and_shows_the_locked_winner():
    """Once someone crosses the threshold the week is over: the card must
    show that winner, not whoever is top of the live standings now."""
    winner, latecomer = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _service(
        standings=[(latecomer, 900, now)], participants=[winner, latecomer]
    )
    repo.get_current_sprint_winner_row.return_value = (winner, 500, now)

    data = service.card_data(now)

    assert data["finished"] is True
    assert data["leader"] == (winner, 500)


def test_card_counts_participants_who_have_not_registered_yet():
    """"из N" is how many people paid to enter, so allowlist entries that
    are still just a phone number count too."""
    service, repo = _service(participants=[uuid4()])
    repo.count_participants.return_value = 12  # 1 registered + 11 phones
    data = service.card_data(datetime(2026, 7, 22, 10, 0, tzinfo=UTC))
    assert data["participants_total"] == 12


# --------------------------------------------------------------------
# threshold gate
# --------------------------------------------------------------------


def _points_service(*, target, participants, weekly):
    from leaderboard_points.service import LeaderboardPointsService

    repo = MagicMock()
    repo.get_or_create_settings.return_value = MagicMock(sprint_target_points=target)
    repo.participant_user_ids.return_value = participants
    repo.weekly_points.return_value = weekly
    repo.db = MagicMock()
    return LeaderboardPointsService(repo), repo


def test_non_participant_never_wins_even_after_crossing_the_threshold(monkeypatch):
    outsider = uuid4()
    service, repo = _points_service(target=500, participants=[], weekly=[])

    service.check_and_lock_sprint_winner(outsider, total_points_after=9_000)

    repo.try_lock_sprint_winner.assert_not_called()


def test_threshold_is_compared_against_weekly_points_not_all_time_total(monkeypatch):
    """A veteran with 9 000 lifetime points who earned only 10 this week
    must not win a 500-point weekly sprint."""
    player = uuid4()
    now = datetime.now(UTC)
    service, repo = _points_service(
        target=500, participants=[player], weekly=[(player, 10, now)]
    )
    monkeypatch.setattr(
        "quiz.repositories.leaderboard_hidden.LeaderboardHiddenRepository",
        lambda _db: MagicMock(get_all=lambda: []),
    )

    service.check_and_lock_sprint_winner(player, total_points_after=9_000)

    repo.try_lock_sprint_winner.assert_not_called()


def test_participant_wins_when_weekly_points_reach_the_threshold(monkeypatch):
    player = uuid4()
    now = datetime.now(UTC)
    service, repo = _points_service(
        target=500, participants=[player], weekly=[(player, 520, now)]
    )
    monkeypatch.setattr(
        "quiz.repositories.leaderboard_hidden.LeaderboardHiddenRepository",
        lambda _db: MagicMock(get_all=lambda: []),
    )

    service.check_and_lock_sprint_winner(player, total_points_after=9_000)

    repo.try_lock_sprint_winner.assert_called_once()
    _, locked_user, locked_points = repo.try_lock_sprint_winner.call_args[0]
    assert locked_user == player
    assert locked_points == 520, "records the weekly score, not the lifetime total"


def test_threshold_check_short_circuits_when_lifetime_total_is_below_target():
    """Cheap guard: weekly points can never exceed the all-time total, so
    a low total skips the aggregate query entirely."""
    player = uuid4()
    service, repo = _points_service(target=500, participants=[player], weekly=[])

    service.check_and_lock_sprint_winner(player, total_points_after=100)

    repo.weekly_points.assert_not_called()
    repo.try_lock_sprint_winner.assert_not_called()


# --------------------------------------------------------------------
# integrity holes closed alongside CRM #19
# --------------------------------------------------------------------


def _points_repo(frozen: bool):
    """UserPointsRepository over a mocked session whose risk-profile query
    reports `frozen`."""
    from quiz.repositories.user_points import UserPointsRepository

    session = MagicMock()
    session.query.return_value.filter.return_value.scalar.return_value = frozen
    return UserPointsRepository(session), session


def test_frozen_user_earns_nothing_from_any_source():
    """The freeze used to be enforced only in the ЕНТ award path, so battle
    wins and referral rewards kept crediting a user the admin had frozen for
    fraud. With CRM #19 those points decide a cash prize."""
    repo, session = _points_repo(frozen=True)

    repo.add_points(uuid4(), 50, source_type="battle")

    session.execute.assert_not_called()
    session.add.assert_not_called()


def test_unfrozen_user_still_earns_normally():
    repo, session = _points_repo(frozen=False)

    repo.add_points(uuid4(), 50, source_type="battle")

    session.execute.assert_called()


def test_admin_adjustment_triggers_the_sprint_winner_check():
    """Manual adjustments bypass add_points, where the hook normally fires —
    without an explicit call an admin could push a participant over the
    weekly threshold and no winner would be locked in."""
    from leaderboard_points.service import LeaderboardPointsService

    repo = MagicMock()
    repo.adjust_user_points.return_value = (100, 700)
    service = LeaderboardPointsService(repo)
    service.check_and_lock_sprint_winner = MagicMock()
    user_id = uuid4()

    service.adjust_points(user_id, 600, "приз за конкурс", None, "admin@aima.kz")

    service.check_and_lock_sprint_winner.assert_called_once_with(user_id, 700)


def test_settings_dto_returns_every_sprint_field_it_stores():
    """Regression: the card copy and prize were saved to the DB but missing
    from `_to_dto`, so the API read them back as null. The admin page loads
    settings into its inputs — blank inputs then wiped the real values on the
    next save. Anything writable must survive the round trip."""
    from datetime import UTC, datetime as _dt

    from leaderboard_points.service import _to_dto

    settings = MagicMock(
        auto_reset_enabled=False,
        reset_mode="interval",
        interval_days=30,
        last_reset_at=None,
        sprint_target_points=500,
        sprint_title_ru="Еженедельный спринт",
        sprint_title_kk="Апталық спринт",
        sprint_prize_amount=50_000,
        sprint_access_url="https://wa.me/77001234567",
        updated_at=_dt.now(UTC),
        updated_by="admin@aima.kz",
    )

    dto = _to_dto(settings)

    assert dto.sprint_target_points == 500
    assert dto.sprint_title_ru == "Еженедельный спринт"
    assert dto.sprint_title_kk == "Апталық спринт"
    assert dto.sprint_prize_amount == 50_000
    assert dto.sprint_access_url == "https://wa.me/77001234567"


# --------------------------------------------------------------------
# ranked standings + movement delta (weekly-sprint screen)
# --------------------------------------------------------------------


def _standings_service(*, standings, participants, prev_ranks, prize=50_000):
    repo = MagicMock()
    repo.weekly_points.return_value = standings
    repo.participant_user_ids.return_value = participants
    repo.count_participants.return_value = len(participants)
    repo.latest_snapshot_ranks.return_value = prev_ranks
    repo.get_current_sprint_winner_row.return_value = None
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_prize_amount=prize, sprint_title_ru="Спринт", sprint_title_kk="Спринт",
        sprint_open_to_all=False,
    )
    service = SprintService(repo)
    service._eligible_user_ids = lambda: participants
    return service, repo


def test_standings_are_ranked_one_based_best_first():
    a, b, c = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, _ = _standings_service(
        standings=[(a, 500, now), (b, 300, now), (c, 100, now)],
        participants=[a, b, c],
        prev_ranks={},
    )
    entries = service.ranked_standings(now)["entries"]
    assert [(uid, rank) for uid, _, rank, _ in entries] == [(a, 1), (b, 2), (c, 3)]


def test_standings_expose_winner_and_finished_when_threshold_taken():
    """When the week has an early threshold winner, ranked_standings marks
    finished and names that winner (id + points) — even if someone else now
    leads on points, the winner is the one who took the week."""
    a, b = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _standings_service(
        standings=[(b, 900, now), (a, 800, now)],  # b now leads on points
        participants=[a, b],
        prev_ranks={},
    )
    # ...but `a` took the early-win threshold at 800.
    repo.get_current_sprint_winner_row.return_value = (a, 800, now)
    data = service.ranked_standings(now)
    assert data["finished"] is True
    assert data["winner"] == (a, 800)


def test_standings_have_no_winner_while_week_is_live():
    a = uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, _ = _standings_service(
        standings=[(a, 500, now)], participants=[a], prev_ranks={}
    )
    data = service.ranked_standings(now)
    assert data["finished"] is False
    assert data["winner"] is None


def test_delta_is_positive_when_a_user_climbs_since_the_morning():
    a, b = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    # This morning a was 2nd, b was 1st; now a leads.
    service, _ = _standings_service(
        standings=[(a, 900, now), (b, 800, now)],
        participants=[a, b],
        prev_ranks={a: 2, b: 1},
    )
    by_user = {uid: delta for uid, _, _, delta in service.ranked_standings(now)["entries"]}
    assert by_user[a] == 1   # 2nd → 1st, up one
    assert by_user[b] == -1  # 1st → 2nd, down one


def test_delta_is_null_on_the_first_day_with_no_prior_snapshot():
    a, b = uuid4(), uuid4()
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    service, _ = _standings_service(
        standings=[(a, 500, now), (b, 300, now)],
        participants=[a, b],
        prev_ranks={},  # nothing recorded yet
    )
    assert all(d is None for _, _, _, d in service.ranked_standings(now)["entries"])


def test_snapshot_is_skipped_when_already_captured_today():
    a = uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _standings_service(
        standings=[(a, 500, now)], participants=[a], prev_ranks={}
    )
    repo.snapshot_exists_for_day.return_value = True
    assert service.capture_rank_snapshot(now)["ran"] is False
    repo.save_rank_snapshot.assert_not_called()


def test_snapshot_records_current_ranks_when_due():
    a, b = uuid4(), uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _standings_service(
        standings=[(a, 500, now), (b, 300, now)], participants=[a, b], prev_ranks={}
    )
    repo.snapshot_exists_for_day.return_value = False
    result = service.capture_rank_snapshot(now)
    assert result == {"ran": True, "captured": 2}
    _, _, ranks = repo.save_rank_snapshot.call_args[0]
    assert ranks == [(a, 1), (b, 2)]


def test_latest_snapshot_ranks_builds_a_valid_query():
    """Regression: `func.max` was used in the repo without importing `func`,
    which mocked-repo tests never exercised — it only blew up (NameError,
    500) when the real repository ran. This drives the real method with a
    mock session so a missing import fails here, not in production."""
    from datetime import UTC, datetime as _dt

    from leaderboard_points.repository import LeaderboardPointsRepository

    session = MagicMock()
    session.query.return_value.filter.return_value.scalar.return_value = None
    repo = LeaderboardPointsRepository(session)

    # No prior snapshot → empty dict, and — crucially — no NameError while
    # constructing the func.max() query.
    result = repo.latest_snapshot_ranks(
        _dt(2026, 7, 20, tzinfo=UTC), _dt(2026, 7, 22, tzinfo=UTC)
    )
    assert result == {}


def test_ranked_standings_exposes_access_url_for_the_buy_button():
    a = uuid4()
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    service, repo = _standings_service(
        standings=[(a, 500, now)], participants=[a], prev_ranks={}
    )
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_prize_amount=50_000,
        sprint_title_ru="Спринт",
        sprint_title_kk="Спринт",
        sprint_access_url="https://wa.me/77001234567",
    )
    assert service.ranked_standings(now)["access_url"] == "https://wa.me/77001234567"


def test_is_participant_delegates_to_the_allowlist():
    a = uuid4()
    service, repo = _standings_service(standings=[], participants=[a], prev_ranks={})
    repo.is_participant.return_value = True
    assert service.is_participant(a) is True
    repo.is_participant.assert_called_once_with(a)


def test_is_participant_open_to_all_bypasses_allowlist():
    """sprint_open_to_all on → everyone is a participant (free sprint), the
    allowlist is not even consulted."""
    service, repo = _standings_service(standings=[], participants=[], prev_ranks={})
    repo.get_or_create_settings.return_value.sprint_open_to_all = True
    repo.is_participant.return_value = False  # not on the allowlist
    assert service.is_participant(uuid4()) is True
    repo.is_participant.assert_not_called()


# --------------------------------------------------------------------
# sprint test: per-answer scoring
# --------------------------------------------------------------------


def _answer_service(*, per_answer, correct_ids, already=False, weekly_after=None):
    repo = MagicMock()
    repo.get_or_create_settings.return_value = MagicMock(
        sprint_points_per_answer=per_answer,
        sprint_target_points=None,  # threshold off — winner check short-circuits
    )
    repo.correct_variant_ids.return_value = set(correct_ids)
    repo.sprint_answer_already_scored.return_value = already
    repo.record_sprint_answer_points.return_value = True  # not frozen
    repo.weekly_points.return_value = weekly_after or []
    repo.db = MagicMock()
    return SprintService(repo), repo


def test_correct_answer_awards_configured_points():
    player = uuid4()
    now = datetime.now(UTC)
    service, repo = _answer_service(
        per_answer=10, correct_ids=[7], weekly_after=[(player, 40, now)]
    )

    result = service.score_answer(player, question_id=99, variant_ids=[7])

    assert result["correct"] is True
    assert result["awarded"] == 10
    assert result["week_points"] == 40
    # Credited through the ISOLATED sprint path, NOT the shared add_points
    # (which would also bump the global total_points).
    repo.record_sprint_answer_points.assert_called_once()


def test_wrong_answer_awards_nothing():
    player = uuid4()
    service, repo = _answer_service(per_answer=10, correct_ids=[7])

    result = service.score_answer(player, question_id=99, variant_ids=[3])

    assert result["correct"] is False
    assert result["awarded"] == 0
    repo.record_sprint_answer_points.assert_not_called()


def test_frozen_user_earns_no_sprint_points():
    """An admin-frozen user's correct answer credits nothing — the repo
    returns False, so awarded stays 0 even though the answer was right."""
    player = uuid4()
    service, repo = _answer_service(per_answer=10, correct_ids=[7])
    repo.record_sprint_answer_points.return_value = False  # frozen

    result = service.score_answer(player, question_id=99, variant_ids=[7])

    assert result["correct"] is True
    assert result["awarded"] == 0


def test_replayed_answer_is_not_scored_twice():
    """Anti-abuse: the same correct answer, resubmitted, earns nothing —
    a flaky-connection retry can't double-credit and neither can a farmer."""
    player = uuid4()
    now = datetime.now(UTC)
    service, repo = _answer_service(
        per_answer=10, correct_ids=[7], already=True, weekly_after=[(player, 10, now)]
    )

    result = service.score_answer(player, question_id=99, variant_ids=[7])

    assert result["correct"] is True
    assert result["awarded"] == 0, "already scored this week"
    repo.record_sprint_answer_points.assert_not_called()


def test_per_attempt_scoring_uses_test_scoped_source_id():
    """With a test_id the idempotency key AND the audit source_id are scoped to
    the attempt ("{test_id}:{question_id}"), so the same question in a new test
    scores again while a re-tap in the same test still can't double-credit."""
    player = uuid4()
    now = datetime.now(UTC)
    service, repo = _answer_service(
        per_answer=10, correct_ids=[7], weekly_after=[(player, 10, now)]
    )

    result = service.score_answer(
        player, question_id=99, variant_ids=[7], test_id=504
    )

    assert result["awarded"] == 10
    # Both the idempotency lookup and the written audit row are keyed by the
    # attempt-scoped source id, not the bare question id.
    already_args = repo.sprint_answer_already_scored.call_args
    assert "504:99" in (list(already_args.args) + list(already_args.kwargs.values()))
    rec_args = repo.record_sprint_answer_points.call_args
    assert "504:99" in (list(rec_args.args) + list(rec_args.kwargs.values()))


def test_answer_scoring_disabled_when_per_answer_zero():
    player = uuid4()
    service, repo = _answer_service(per_answer=0, correct_ids=[7])
    result = service.score_answer(player, question_id=99, variant_ids=[7])
    assert result["awarded"] == 0
    repo.record_sprint_answer_points.assert_not_called()
