"""Pin LeaderboardPrize DTO validation + service business rules.

The mutable surface (admin CRUD) is small but easy to break — a bad
icon_key validator regex would let the client receive a key it
can't render and crash the leaderboard screen. These tests lock the
contract.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

# Pull mappers so SQLAlchemy resolves cross-module relationships
# without needing a live engine.
import quiz.models  # noqa: F401
import student.models  # noqa: F401

from leaderboard_prizes.dtos import (
    LeaderboardPrizeCreateDTO,
    LeaderboardPrizeUpdateDTO,
    PRIZE_ICON_KEYS,
)
from leaderboard_prizes.service import LeaderboardPrizeService


def _fake_prize(**overrides):
    base = dict(
        id=1,
        rank=1,
        icon_key="trophy",
        title="1 место",
        description="—",
        is_active=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_service(repo_mock=None):
    repo = repo_mock or MagicMock()
    repo.db = MagicMock()
    return LeaderboardPrizeService(repo=repo)


# ─── DTO validation ──────────────────────────────────────────────────


class TestCreateDTOValidation:
    def test_accepts_all_known_icon_keys(self):
        for key in PRIZE_ICON_KEYS:
            dto = LeaderboardPrizeCreateDTO(
                rank=1, icon_key=key, title="t",
            )
            assert dto.icon_key == key

    def test_rejects_unknown_icon_key(self):
        with pytest.raises(ValidationError) as e:
            LeaderboardPrizeCreateDTO(rank=1, icon_key="banana", title="t")
        assert "icon_key" in str(e.value).lower()

    def test_rank_must_be_positive(self):
        with pytest.raises(ValidationError):
            LeaderboardPrizeCreateDTO(rank=0, icon_key="trophy", title="t")
        with pytest.raises(ValidationError):
            LeaderboardPrizeCreateDTO(rank=-5, icon_key="trophy", title="t")

    def test_rank_capped_at_100(self):
        # Anything above 100 is almost certainly a typo (we don't run
        # a top-1000 board). Cap protects the leaderboard screen from
        # rendering a ridiculous «rank #50000» card.
        with pytest.raises(ValidationError):
            LeaderboardPrizeCreateDTO(rank=101, icon_key="trophy", title="t")

    def test_title_required(self):
        with pytest.raises(ValidationError):
            LeaderboardPrizeCreateDTO(rank=1, icon_key="trophy", title="")

    def test_description_default_empty(self):
        dto = LeaderboardPrizeCreateDTO(rank=1, icon_key="trophy", title="t")
        assert dto.description == ""


class TestUpdateDTOValidation:
    def test_all_fields_optional(self):
        dto = LeaderboardPrizeUpdateDTO()
        assert dto.rank is None
        assert dto.icon_key is None
        assert dto.title is None

    def test_icon_key_none_is_allowed(self):
        # «not changing the icon» path
        dto = LeaderboardPrizeUpdateDTO(title="new title")
        assert dto.icon_key is None

    def test_invalid_icon_key_rejected_even_in_patch(self):
        with pytest.raises(ValidationError):
            LeaderboardPrizeUpdateDTO(icon_key="banana")


# ─── service logic ───────────────────────────────────────────────────


class TestServiceGetOne:
    def test_404_when_missing(self):
        repo = MagicMock()
        repo.get.return_value = None
        svc = _make_service(repo)
        with pytest.raises(HTTPException) as e:
            svc.get_one(42)
        assert e.value.status_code == 404
        assert "не найден" in e.value.detail


class TestServiceCreate:
    def test_persists_and_returns(self):
        repo = MagicMock()
        svc = _make_service(repo)
        payload = LeaderboardPrizeCreateDTO(
            rank=1, icon_key="trophy", title="1 место",
        )
        svc.create(payload)
        # repository.create called with a LeaderboardPrize instance
        assert repo.create.called
        instance = repo.create.call_args[0][0]
        assert instance.rank == 1
        assert instance.icon_key == "trophy"

    def test_rank_uniqueness_409(self):
        repo = MagicMock()
        # Simulate the IntegrityError path — DB rejected duplicate rank
        repo.create.side_effect = IntegrityError(
            "stmt",
            params=None,
            orig=Exception("duplicate key value violates unique constraint "
                           "\"uq_leaderboard_prizes_rank\""),
        )
        svc = _make_service(repo)
        with pytest.raises(HTTPException) as e:
            svc.create(LeaderboardPrizeCreateDTO(
                rank=1, icon_key="trophy", title="dup",
            ))
        assert e.value.status_code == 409
        assert "#1" in e.value.detail


class TestServiceUpdate:
    def test_partial_patch_only_touches_listed_fields(self):
        repo = MagicMock()
        prize = _fake_prize(title="old", description="old-desc")
        repo.get.return_value = prize
        svc = _make_service(repo)

        svc.update(1, LeaderboardPrizeUpdateDTO(title="new"))
        assert prize.title == "new"
        # description NOT touched
        assert prize.description == "old-desc"

    def test_is_active_can_be_flipped(self):
        repo = MagicMock()
        prize = _fake_prize(is_active=True)
        repo.get.return_value = prize
        svc = _make_service(repo)
        svc.update(1, LeaderboardPrizeUpdateDTO(is_active=False))
        assert prize.is_active is False


class TestPublicListing:
    def test_list_active_is_repository_passthrough(self):
        repo = MagicMock()
        repo.list_active.return_value = [_fake_prize(rank=1), _fake_prize(rank=2)]
        svc = _make_service(repo)
        out = svc.list_active_prizes()
        assert len(out) == 2
        repo.list_active.assert_called_once()
