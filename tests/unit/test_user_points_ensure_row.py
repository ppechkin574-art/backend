"""UserPointsRepository.ensure_user_row() — new users must show up in the
global leaderboard immediately, not only after their first points-earning
action.

Root cause fixed here: a UserPoints row was previously only ever created
lazily inside add_points()'s upsert (battle win / referral / full-ЕНТ
completion). Neither complete_registration() (SMS/WhatsApp) nor OAuth
registration created one, and get_all_ranked()/get_user_rank() query
`FROM user_points` with no join back to the full user population — so a
brand-new 0-point user was structurally absent from the leaderboard, not
merely "shown with 0". ensure_user_row() is called from both registration
routes (see api/routes/auth/routes.py) to close that gap.
"""

from unittest.mock import MagicMock
from uuid import uuid4

from quiz.repositories.user_points import UserPointsRepository


def test_ensure_user_row_inserts_zero_point_row_on_conflict_do_nothing():
    session = MagicMock()
    user_id = uuid4()

    UserPointsRepository(session).ensure_user_row(user_id)

    assert session.execute.call_count == 1
    stmt, params = session.execute.call_args.args
    sql_text = str(stmt)
    assert "INSERT INTO user_points" in sql_text
    assert "ON CONFLICT (user_id) DO NOTHING" in sql_text
    assert params == {"user_id": user_id}
    session.commit.assert_called_once()


def test_ensure_user_row_is_safe_to_call_twice_for_the_same_user():
    # Real behaviour relies on the DB-level ON CONFLICT DO NOTHING (not
    # exercised against a real Postgres here — see the SQL-shape assertion
    # above); this just guards that calling it twice from Python's side
    # (e.g. registration retried, or an OAuth login for an existing user)
    # doesn't raise or double-commit oddly.
    session = MagicMock()
    user_id = uuid4()
    repo = UserPointsRepository(session)

    repo.ensure_user_row(user_id)
    repo.ensure_user_row(user_id)

    assert session.execute.call_count == 2
    assert session.commit.call_count == 2
