"""add FK constraints on user_points and user_relationships

Roman's three migrations created user_points and user_relationships without
foreign keys to students.id. If a Student row is deleted, orphaned rows
remain in those tables. This migration:

  1) cleans up any orphan rows already present (defensive — should be empty
     in a fresh prod DB, but the dump-based seed is a known wildcard)
  2) adds 4 ON DELETE CASCADE foreign keys

Revision ID: 2a5acb79a88d
Revises: 58ec4f7a3d2b
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2a5acb79a88d"
down_revision: Union[str, Sequence[str], None] = "58ec4f7a3d2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) clean up orphans
    op.execute(
        """
        DELETE FROM user_points
         WHERE user_id NOT IN (SELECT id FROM students);
        """
    )
    op.execute(
        """
        DELETE FROM user_relationships
         WHERE parent_id NOT IN (SELECT id FROM students)
            OR child_id  NOT IN (SELECT id FROM students)
            OR (inviter_id IS NOT NULL
                AND inviter_id NOT IN (SELECT id FROM students));
        """
    )

    # 2) add FK constraints with cascade delete
    op.create_foreign_key(
        "fk_user_points_user_id_students",
        "user_points",
        "students",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_user_relationships_parent_id_students",
        "user_relationships",
        "students",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_user_relationships_child_id_students",
        "user_relationships",
        "students",
        ["child_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_user_relationships_inviter_id_students",
        "user_relationships",
        "students",
        ["inviter_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_relationships_inviter_id_students",
        "user_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_user_relationships_child_id_students",
        "user_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_user_relationships_parent_id_students",
        "user_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_user_points_user_id_students",
        "user_points",
        type_="foreignkey",
    )
