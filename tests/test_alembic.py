"""Alembic structural sanity — runs offline (no DB connection)."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config("alembic.ini"))


def test_alembic_has_exactly_one_head():
    heads = _script().get_heads()
    assert len(heads) == 1, f"Expected 1 alembic head, got {heads}"


def test_alembic_history_is_linear():
    """No diverging branches: every revision (except the root) must have
    exactly one down_revision."""
    script = _script()
    for rev in script.walk_revisions():
        # rev.down_revision is None for the root, str for single parent,
        # tuple for merge revisions. We forbid merge revisions to keep
        # the chain linear.
        assert not isinstance(rev.down_revision, tuple), (
            f"Migration {rev.revision} has multiple parents — diverged history"
        )


def test_alembic_can_resolve_full_chain_from_root_to_head():
    script = _script()
    head = script.get_heads()[0]
    revisions = list(script.walk_revisions(head=head))
    # Sanity: should be at least 30 revisions in our chain by 04.05.2026.
    assert len(revisions) >= 30, (
        f"Suspicious: only {len(revisions)} migrations in chain, expected 30+"
    )
