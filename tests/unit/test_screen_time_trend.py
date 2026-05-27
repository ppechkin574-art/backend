"""Tests for StatisticService._compute_screen_time_trend.

Background (27.05.2026): the «↓ X%» chip on the stats screen kept
appearing as ↓99% for accounts whose recent half of the week was near-
zero — that's the real math, but easy to mistake for a bug. These tests
pin the contract so future tweaks (e.g. raising the floor, switching
the split, dropping the clamp) don't silently change what the badge
shows.

Tests intentionally cover the empty/short-history paths because earlier
versions of this function returned different sentinels (0 vs None) and
the UI hides the badge on None only.
"""

from quiz.services.statistic import StatisticService


def _hist(values: list[int]) -> list[dict]:
    """Shape a list of ints into the same dict layout the service
    passes in production — `_compute_screen_time_trend` reads only the
    `screen_time_seconds` key, so date is irrelevant."""
    return [
        {"date": f"2026-05-{20 + i:02d}", "screen_time_seconds": v}
        for i, v in enumerate(values)
    ]


class TestComputeScreenTimeTrend:
    """All cases live in one class so they share the `compute` helper —
    keeps each test body to the essential numeric arithmetic."""

    compute = staticmethod(StatisticService._compute_screen_time_trend)

    # ─── insufficient data ────────────────────────────────────────────

    def test_none_for_empty_history(self):
        assert self.compute([]) is None

    def test_none_for_none_history(self):
        assert self.compute(None) is None  # type: ignore[arg-type]

    def test_none_when_fewer_than_4_days(self):
        # Earlier code accepted 2-vs-2; spec now floors at 4 days total
        # so a single day's anomaly doesn't fire the chip.
        assert self.compute(_hist([100, 200, 300])) is None

    def test_returns_value_at_4_days(self):
        # 4 days = the minimum that satisfies the «split in half» rule.
        # Prior=[100,100], recent=[200,200] → +100%.
        assert self.compute(_hist([100, 100, 200, 200])) == 99  # clamped

    # ─── zero-division guard ──────────────────────────────────────────

    def test_none_when_prior_half_all_zero(self):
        # First half all zero → division blows up; suppress instead of
        # returning ±inf so the UI doesn't render a garbage badge.
        assert self.compute(_hist([0, 0, 0, 5000, 5000, 5000])) is None

    def test_value_when_only_recent_half_zero(self):
        # Symmetric case: prior non-zero, recent zero. Should give a
        # huge drop, clamped to -99.
        result = self.compute(_hist([5000, 5000, 5000, 0, 0, 0]))
        assert result == -99

    # ─── ordinary deltas ──────────────────────────────────────────────

    def test_realistic_drop_clamps_to_minus_99(self):
        # Mirrors the actual prod data that triggered this whole work
        # item (operator's account 21–27 May).
        items = [5862, 25319, 16230, 27, 2, 36, 6]
        # split: prior=[5862,25319,16230] (avg 15803), recent=[27,2,36,6] (avg 17)
        # delta ≈ -99.9% → clamped to -99
        assert self.compute(_hist(items)) == -99

    def test_modest_drop_uncramped(self):
        # 2400 → 1200 = -50%. Far below the clamp; should be reported
        # as-is, not snapped to a round value.
        items = [2400, 2400, 2400, 1200, 1200, 1200]
        assert self.compute(_hist(items)) == -50

    def test_modest_growth_uncramped(self):
        # 1200 → 1800 = +50%.
        items = [1200, 1200, 1200, 1800, 1800, 1800]
        assert self.compute(_hist(items)) == 50

    def test_growth_clamped_to_99(self):
        # Tiny prior, huge recent — anything above +99 should snap.
        items = [10, 10, 10, 9000, 9000, 9000]
        assert self.compute(_hist(items)) == 99

    # ─── equal halves ──────────────────────────────────────────────────

    def test_none_when_delta_rounds_to_zero(self):
        # Identical halves → 0% change → suppress (so the chip doesn't
        # render a meaningless «0%» indicator).
        items = [1000, 1000, 1000, 1000, 1000, 1000]
        assert self.compute(_hist(items)) is None

    def test_subtle_change_below_rounding_threshold_is_none(self):
        # +0.4% rounds to 0 → suppress. Catches floating-point noise.
        items = [1000, 1000, 1000, 1004, 1004, 1004]
        assert self.compute(_hist(items)) is None

    # ─── split logic for odd-length windows ───────────────────────────

    def test_split_at_floor_division_for_odd_length(self):
        # 7 entries → mid = 7 // 2 = 3.
        # prior = first 3, recent = last 4.
        # avg(prior=[100,100,100])=100, avg(recent=[200,200,200,200])=200
        # delta = +100% → clamped to 99.
        items = [100, 100, 100, 200, 200, 200, 200]
        assert self.compute(_hist(items)) == 99

    # ─── input shape resilience ───────────────────────────────────────

    def test_handles_missing_field_as_zero(self):
        # Defensive: backend repository should always populate
        # `screen_time_seconds` but if it ever ships a row missing the
        # key the helper must not crash — treat as 0.
        items = [
            {"date": "2026-05-20", "screen_time_seconds": 100},
            {"date": "2026-05-21"},  # missing → treated as 0
            {"date": "2026-05-22", "screen_time_seconds": 100},
            {"date": "2026-05-23", "screen_time_seconds": 200},
            {"date": "2026-05-24", "screen_time_seconds": 200},
        ]
        # prior=[100,0]=avg 50, recent=[100,200,200]=avg 166.7 → +233% → +99
        assert self.compute(items) == 99

    def test_handles_none_screen_time_field(self):
        # Same defensive guard — None → 0.
        items = [
            {"date": "2026-05-20", "screen_time_seconds": None},
            {"date": "2026-05-21", "screen_time_seconds": 100},
            {"date": "2026-05-22", "screen_time_seconds": 100},
            {"date": "2026-05-23", "screen_time_seconds": 100},
        ]
        # prior=[0,100]=avg 50, recent=[100,100]=avg 100 → +100% → +99
        assert self.compute(items) == 99
