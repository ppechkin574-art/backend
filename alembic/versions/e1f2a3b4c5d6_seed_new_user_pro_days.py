"""seed new_user_pro_days app setting

Revision ID: e1f2a3b4c5d6
Revises: b9c8d7e6f5a4
Create Date: 2026-06-30 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SETTING = {
    "key": "new_user_pro_days",
    "value": "0",
    "description": (
        "Количество дней PRO-подписки, выдаваемых новым пользователям автоматически "
        "при регистрации. 0 = функция отключена (стандартный 1 день пробного периода)."
    ),
}


def upgrade() -> None:
    app_settings = sa.table(
        "app_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(app_settings, [SETTING])


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'new_user_pro_days'")
