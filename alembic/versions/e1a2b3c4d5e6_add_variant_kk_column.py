"""kk-translation cache column for variants (Phase 7b pilot extension)

Adds one nullable column on `variants` mirroring the question-side kk
fields shipped in `a7c4f9e1b2d8`:

  * variants.variant_text_kk  — denormalised Kazakh body text per
                                variant.  Read by the api-side locale
                                resolver alongside question_text_kk
                                when Accept-Language: kk; null falls
                                back to building text from the
                                `TextBlockLink.blocks` chain as before.

Ships empty for the whole catalogue.  The companion data migration
`e7d8c9b1a2f3` populates the ~746 Mathematics variants only (the same
scope as the question pilot).  Other subjects fall back to RU on read.

Revision ID: e1a2b3c4d5e6
Revises: c4e9d6f7b8a2
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c4e9d6f7b8a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "variants",
        sa.Column("variant_text_kk", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("variants", "variant_text_kk")
