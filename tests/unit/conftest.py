"""Unit-test fixtures."""

import pytest

from api.middlewares.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset slowapi's in-process counter before each unit test.

    The limiter's MemoryStorage otherwise accumulates across the whole session,
    so the many /verify calls scattered through the payment tests eventually trip
    the 20/min limit and flake *unrelated* tests (depending on order + minute
    boundary). Resetting per test gives every test a clean window; the dedicated
    rate-limit tests still exercise their own scenario from zero.
    """
    limiter.reset()
    yield
