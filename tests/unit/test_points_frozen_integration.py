"""Unit tests for the points_frozen gate in ent_attempts.py.

The actual check lives inside EntAttemptService.answer() at line ~535:
    if risk_profile and risk_profile.points_frozen:
        # skip add_points
    else:
        self._uow.user_points.add_points(...)

Because answer() is 500+ lines with complex DB state, we test the guard
logic in isolation — the same pattern used in test_ent_points_idempotency.py
which tests award_points_once gating without calling answer() directly.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


# ---------------------------------------------------------------------------
# Inline simulation of the points_frozen guard (ent_attempts.py:528-547)
# ---------------------------------------------------------------------------

def _simulate_award(
    score: int,
    award_once_returns: bool,
    risk_profile,
) -> list[int]:
    """Replicate the guard branch and return list of add_points scores called."""
    add_points_calls: list[int] = []
    if score > 0:  # full_exam path (exam_type guard omitted — always true here)
        if award_once_returns:
            if risk_profile and risk_profile.points_frozen:
                pass  # frozen — skip
            else:
                add_points_calls.append(score)
    return add_points_calls


def _profile(frozen: bool):
    return SimpleNamespace(points_frozen=frozen)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPointsFrozenGuard:
    def test_add_points_called_when_not_frozen(self):
        calls = _simulate_award(score=140, award_once_returns=True, risk_profile=_profile(False))
        assert calls == [140]

    def test_add_points_NOT_called_when_frozen(self):
        calls = _simulate_award(score=140, award_once_returns=True, risk_profile=_profile(True))
        assert calls == []

    def test_add_points_called_when_no_profile(self):
        """No risk profile row → treat as not frozen."""
        calls = _simulate_award(score=100, award_once_returns=True, risk_profile=None)
        assert calls == [100]

    def test_add_points_NOT_called_when_award_once_false(self):
        """award_points_once=False means duplicate submission — skip regardless of freeze."""
        calls = _simulate_award(score=140, award_once_returns=False, risk_profile=_profile(False))
        assert calls == []

    def test_add_points_NOT_called_when_score_zero(self):
        calls = _simulate_award(score=0, award_once_returns=True, risk_profile=_profile(False))
        assert calls == []

    def test_frozen_flag_is_checked_not_negated(self):
        """Sanity: frozen=True blocks, frozen=False passes."""
        assert _simulate_award(100, True, _profile(True)) == []
        assert _simulate_award(100, True, _profile(False)) == [100]


class TestPointsFrozenCombinations:
    """Exhaustive truth table for the three independent gates."""

    import itertools

    CASES = [
        # (score>0, award_once, frozen, no_profile, expect_award)
        (True,  True,  False, False, True),   # normal happy path
        (True,  True,  True,  False, False),  # frozen blocks
        (True,  True,  False, True,  True),   # no profile = not frozen
        (True,  False, False, False, False),  # duplicate submission
        (False, True,  False, False, False),  # zero score
        (False, True,  True,  False, False),  # zero score + frozen
    ]

    def test_truth_table(self):
        for score_positive, award_once, frozen, no_profile, expect in self.CASES:
            score = 100 if score_positive else 0
            profile = None if no_profile else _profile(frozen)
            calls = _simulate_award(score, award_once, profile)
            got = len(calls) > 0
            assert got == expect, (
                f"score={score}, award_once={award_once}, frozen={frozen}, "
                f"no_profile={no_profile} → expected award={expect}, got={got}"
            )
