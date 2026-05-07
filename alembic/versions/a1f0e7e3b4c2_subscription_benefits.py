"""subscription_benefits table + initial seed (RU + KZ)

Adds the editable bullet-point list shown on the subscription screen.
Also merges the two divergent heads we had before this commit
(`420aa383195e` and `1338a104083a`) so future migrations have a single
linear lineage to extend from.

Seed contains the six bullets that used to be hardcoded in
`subscription_profile_screen.dart::_benefits`. Kazakh translations are
"working" quality (clear, but not literary) — admins can polish them
through the new admin endpoints when desired.

Revision ID: a1f0e7e3b4c2
Revises: 420aa383195e, 1338a104083a
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1f0e7e3b4c2"
down_revision: Union[str, Sequence[str], None] = ("420aa383195e", "1338a104083a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_BENEFITS = [
    {
        "position": 0,
        "title_ru": "Пробное ЕНТ",
        "title_kz": "Сынама ҰБТ",
        "description_ru": "Подготовка к экзамену в формате тестирования",
        "description_kz": "Тестілеу форматында емтиханға дайындық",
    },
    {
        "position": 1,
        "title_ru": "Полный Курс",
        "title_kz": "Толық курс",
        "description_ru": "Комплексное обучение по всем темам с нуля",
        "description_kz": "Барлық тақырыптар бойынша нөлден бастап кешенді оқыту",
    },
    {
        "position": 2,
        "title_ru": "Кешбек",
        "title_kz": "Кэшбэк",
        "description_ru": "Возврат части средств за выполненные задания",
        "description_kz": "Орындалған тапсырмалар үшін қаражаттың бір бөлігін қайтару",
    },
    {
        "position": 3,
        "title_ru": "Ежедневные задания",
        "title_kz": "Күнделікті тапсырмалар",
        "description_ru": "Регулярная практика для закрепления знаний",
        "description_kz": "Білімді бекіту үшін тұрақты практика",
    },
    {
        "position": 4,
        "title_ru": "Повышающий КЕФ",
        "title_kz": "Жоғарылататын КЭФ",
        "description_ru": "Увеличение бонуса за активность и результаты",
        "description_kz": "Белсенділік пен нәтижелер үшін бонусты ұлғайту",
    },
    {
        "position": 5,
        "title_ru": "Родительский доступ",
        "title_kz": "Ата-ана қолжетімділігі",
        "description_ru": "Контроль успеваемости и активности ученика",
        "description_kz": "Оқушының үлгерімі мен белсенділігін бақылау",
    },
]


def upgrade() -> None:
    op.create_table(
        "subscription_benefits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title_ru", sa.String(length=200), nullable=False),
        sa.Column("title_kz", sa.String(length=200), nullable=False),
        sa.Column("description_ru", sa.Text(), nullable=False),
        sa.Column("description_kz", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_subscription_benefits_position",
        "subscription_benefits",
        ["position"],
    )
    op.create_index(
        "ix_subscription_benefits_is_active",
        "subscription_benefits",
        ["is_active"],
    )
    op.create_index(
        "ix_subscription_benefits_active_position",
        "subscription_benefits",
        ["is_active", "position"],
    )

    # Seed default rows so the mobile app shows the same six benefits
    # immediately after deploy (matching what was hardcoded in Flutter).
    benefits_table = sa.table(
        "subscription_benefits",
        sa.column("position", sa.Integer),
        sa.column("title_ru", sa.String),
        sa.column("title_kz", sa.String),
        sa.column("description_ru", sa.Text),
        sa.column("description_kz", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        benefits_table,
        [{**b, "is_active": True} for b in SEED_BENEFITS],
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_benefits_active_position", table_name="subscription_benefits")
    op.drop_index("ix_subscription_benefits_is_active", table_name="subscription_benefits")
    op.drop_index("ix_subscription_benefits_position", table_name="subscription_benefits")
    op.drop_table("subscription_benefits")
