"""Translation preview endpoint: every-Nth sampling + status guard.

The DB query and response shaping mirror the already-tested /export endpoint;
the genuinely new bits are the every-Nth pick (`_pick_sample`) and the status
validation. Both are pure and covered here without a DB.
"""

import pytest
from fastapi import HTTPException

from api.routes.admin.translation import _pick_sample, preview_translations


def test_pick_sample_every_tenth():
    assert _pick_sample(list(range(1, 31)), 10, 50) == [1, 11, 21]


def test_pick_sample_all_when_one():
    assert _pick_sample([1, 2, 3, 4, 5], 1, 50) == [1, 2, 3, 4, 5]


def test_pick_sample_caps_at_limit():
    assert _pick_sample(list(range(1, 100)), 1, 10) == list(range(1, 11))


def test_pick_sample_hard_cap_200():
    assert len(_pick_sample(list(range(1, 500)), 1, 9999)) == 200


def test_pick_sample_zero_and_negative_treated_as_one():
    assert _pick_sample([1, 2, 3], 0, 50) == [1, 2, 3]
    assert _pick_sample([1, 2, 3], -5, 50) == [1, 2, 3]
    assert _pick_sample([1, 2, 3], 1, 0) == [1]  # limit floored to 1


def test_pick_sample_empty():
    assert _pick_sample([], 10, 50) == []


def test_pick_sample_sample_larger_than_list():
    assert _pick_sample([7, 8, 9], 100, 50) == [7]  # only the first


def test_preview_rejects_bad_status():
    with pytest.raises(HTTPException) as ei:
        preview_translations(subject_id=1, status="bogus", session=None)
    assert ei.value.status_code == 400


@pytest.mark.parametrize("status", ["done", "draft"])
def test_preview_valid_status_passes_guard(status):
    # A valid status proceeds past the guard and only fails later when it
    # touches the (None) session — proving the guard let it through.
    with pytest.raises(Exception) as ei:
        preview_translations(subject_id=1, status=status, session=None)
    assert not (isinstance(ei.value, HTTPException) and ei.value.status_code == 400)
