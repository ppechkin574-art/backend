"""SubscriptionBenefitService — locale resolution + admin CRUD.

Covers the service layer that powers /content/subscription-benefits
(public) and /admin/content/subscription-benefits/... (admin). The
public endpoint changed from a hardcoded list to a DB-driven one in
fix(content) 4234d8a; these tests pin that behaviour so a future
regression that accidentally returns hardcoded values trips here.

- list_active_localised('ru') returns title_ru + description_ru.
- list_active_localised('kz') returns title_kz + description_kz.
- KZ falls back to RU when KZ column is empty (defensive against
  future migrations that loosen the NOT NULL constraint).
- Only is_active=True rows are returned to the public endpoint.
- position ordering is honoured.
- Admin CRUD: list_all_admin, get_admin, create, update, delete.
"""

from datetime import datetime, timezone
from typing import Any

import pytest

from content.dtos import SubscriptionBenefitCreateDTO, SubscriptionBenefitUpdateDTO
from content.service import SubscriptionBenefitService


class _FakeRow:
    def __init__(
        self,
        *,
        id: int,
        position: int,
        title_ru: str,
        title_kz: str,
        description_ru: str,
        description_kz: str,
        is_active: bool = True,
    ):
        self.id = id
        self.position = position
        self.title_ru = title_ru
        self.title_kz = title_kz
        self.description_ru = description_ru
        self.description_kz = description_kz
        self.is_active = is_active
        self.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 5, 15, tzinfo=timezone.utc)


class _FakeRepo:
    """Just what SubscriptionBenefitService.list_active_localised /
    list_all_admin / get / create / update / delete touch."""

    def __init__(self, rows: list[_FakeRow] | None = None):
        self.rows = rows or []
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[tuple[int, dict[str, Any]]] = []
        self.delete_calls: list[int] = []

    def list_active(self) -> list[_FakeRow]:
        return [r for r in self.rows if r.is_active]

    def list_all(self) -> list[_FakeRow]:
        return list(self.rows)

    def get(self, benefit_id: int) -> _FakeRow | None:
        return next((r for r in self.rows if r.id == benefit_id), None)

    def create(self, **fields) -> _FakeRow:
        self.create_calls.append(fields)
        new_row = _FakeRow(id=max((r.id for r in self.rows), default=0) + 1, **fields)
        self.rows.append(new_row)
        return new_row

    def update(self, benefit_id: int, **fields) -> _FakeRow | None:
        row = self.get(benefit_id)
        if row is None:
            return None
        self.update_calls.append((benefit_id, fields))
        for k, v in fields.items():
            setattr(row, k, v)
        return row

    def delete(self, benefit_id: int) -> bool:
        row = self.get(benefit_id)
        if row is None:
            return False
        self.delete_calls.append(benefit_id)
        self.rows = [r for r in self.rows if r.id != benefit_id]
        return True


def _seed_rows() -> list[_FakeRow]:
    return [
        _FakeRow(
            id=1, position=0,
            title_ru="Пробное ЕНТ", title_kz="Сынама ҰБТ",
            description_ru="Подготовка к экзамену",
            description_kz="Емтиханға дайындық",
        ),
        _FakeRow(
            id=2, position=1,
            title_ru="Полный Курс", title_kz="Толық курс",
            description_ru="Комплексное обучение",
            description_kz="Кешенді оқыту",
        ),
        _FakeRow(
            id=3, position=2,
            title_ru="Кешбек", title_kz="Кэшбэк",
            description_ru="Возврат средств",
            description_kz="Қаражатты қайтару",
            is_active=False,  # operator removed via admin
        ),
    ]


# ─────────────────────────── public locale resolution ───────────────────────────


def test_list_active_returns_ru_title_and_description():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    result = svc.list_active_localised("ru")

    assert [r.title for r in result] == ["Пробное ЕНТ", "Полный Курс"]
    assert result[0].description == "Подготовка к экзамену"


def test_list_active_returns_kz_title_and_description():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    result = svc.list_active_localised("kz")

    assert [r.title for r in result] == ["Сынама ҰБТ", "Толық курс"]
    assert result[0].description == "Емтиханға дайындық"


def test_kz_falls_back_to_ru_when_kz_columns_are_empty():
    """Migration enforces NOT NULL on title_kz/description_kz today,
    but the service has defensive fallback in case a future migration
    loosens the constraint. Pin that fallback so we don't break it."""
    rows = [
        _FakeRow(
            id=1, position=0,
            title_ru="Russian Title", title_kz="",
            description_ru="Russian desc", description_kz="",
        ),
    ]
    svc = SubscriptionBenefitService(_FakeRepo(rows))

    result = svc.list_active_localised("kz")

    assert result[0].title == "Russian Title"
    assert result[0].description == "Russian desc"


def test_public_list_excludes_inactive_rows():
    """The defining fix from 4234d8a — admin deactivates a row, mobile
    must stop showing it. Hardcoded list ignored is_active; service does not."""
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    result = svc.list_active_localised("ru")
    ids = [r.id for r in result]

    assert 3 not in ids, "inactive row id=3 (Кешбек) leaked to public response"
    assert ids == [1, 2]


def test_public_list_preserves_position_ordering():
    """`position` from the DB is the canonical UI order — admin can
    reorder benefits without renaming them."""
    rows = [
        _FakeRow(id=1, position=2, title_ru="C", title_kz="C", description_ru="c", description_kz="c"),
        _FakeRow(id=2, position=0, title_ru="A", title_kz="A", description_ru="a", description_kz="a"),
        _FakeRow(id=3, position=1, title_ru="B", title_kz="B", description_ru="b", description_kz="b"),
    ]
    # Repo list_active is responsible for ORDER BY, but ensure service preserves
    # whatever order the repo returns.
    repo = _FakeRepo(rows=sorted(rows, key=lambda r: r.position))
    svc = SubscriptionBenefitService(repo)

    result = svc.list_active_localised("ru")
    assert [r.title for r in result] == ["A", "B", "C"]


def test_empty_repo_returns_empty_public_list():
    svc = SubscriptionBenefitService(_FakeRepo(rows=[]))
    assert svc.list_active_localised("ru") == []


# ─────────────────────────── admin CRUD ───────────────────────────


def test_list_all_admin_includes_inactive_rows():
    """Admin UI shows the whole table including deactivated rows so
    operator can toggle them back on. Distinct from the public list."""
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    result = svc.list_all_admin()

    assert len(result) == 3
    assert any(not r.is_active for r in result)


def test_get_admin_returns_dto_when_found():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    result = svc.get_admin(2)

    assert result is not None
    assert result.id == 2
    assert result.title_ru == "Полный Курс"


def test_get_admin_returns_none_for_missing_id():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    assert svc.get_admin(9999) is None


def test_create_inserts_new_row():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    dto = SubscriptionBenefitCreateDTO(
        position=10,
        title_ru="Новая фича",
        title_kz="Жаңа функция",
        description_ru="Что-то",
        description_kz="Бір нәрсе",
        is_active=True,
    )
    result = svc.create(dto)

    assert result.position == 10
    assert result.title_ru == "Новая фича"
    assert len(repo.rows) == 4


def test_update_patches_only_provided_fields():
    """Partial PATCH semantics — exclude_unset means admin can send
    just {is_active: false} without zeroing out the other columns."""
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    dto = SubscriptionBenefitUpdateDTO(is_active=False)
    result = svc.update(1, dto)

    assert result is not None
    # Only is_active was patched, other fields preserved
    assert result.is_active is False
    assert result.title_ru == "Пробное ЕНТ"


def test_update_returns_none_when_row_missing():
    svc = SubscriptionBenefitService(_FakeRepo(rows=[]))
    result = svc.update(9999, SubscriptionBenefitUpdateDTO(position=5))
    assert result is None


def test_delete_removes_row():
    repo = _FakeRepo(_seed_rows())
    svc = SubscriptionBenefitService(repo)

    assert svc.delete(1) is True
    assert all(r.id != 1 for r in repo.rows)


def test_delete_returns_false_for_missing_row():
    svc = SubscriptionBenefitService(_FakeRepo(rows=[]))
    assert svc.delete(9999) is False
