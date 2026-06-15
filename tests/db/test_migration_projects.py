"""Migration test: the ``projects`` table is created with the right shape.

Drives Alembic directly (upgrade to this revision on a raw engine) rather than
``get_or_create_engine``, whose ``Base.metadata.create_all`` fallback would
reconstruct the table from the ORM model and mask a broken migration.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config

_REVISION = "n1a2b3c4d5e6"
_DOWN_REVISION = "m1a2b3c4d5e6"


def _alembic_cfg(uri: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "omnigent/db/migrations")
    cfg.set_main_option("sqlalchemy.url", uri)
    return cfg


def _upgrade(tmp_path: Path) -> sa.Engine:
    """Upgrade a fresh temp DB to this revision via Alembic only; return its engine."""
    uri = f"sqlite:///{tmp_path / 'projects.db'}"
    engine = sa.create_engine(uri)
    alembic_command.upgrade(_alembic_cfg(uri), _REVISION)
    return engine


def test_projects_table_has_expected_columns(tmp_path: Path) -> None:
    """Upgrading to this revision creates ``projects`` with all columns."""
    inspector = sa.inspect(_upgrade(tmp_path))
    assert "projects" in inspector.get_table_names()
    columns = {col["name"] for col in inspector.get_columns("projects")}
    assert columns == {
        "id",
        "owner",
        "name",
        "workspace",
        "agent",
        "harness",
        "model",
        "created_at",
        "updated_at",
    }


def test_projects_unique_constraint_and_index(tmp_path: Path) -> None:
    """The ``(owner, name)`` unique constraint and the owner index are created."""
    inspector = sa.inspect(_upgrade(tmp_path))
    uniques = inspector.get_unique_constraints("projects")
    assert any(set(u["column_names"]) == {"owner", "name"} for u in uniques)
    index_names = {ix["name"] for ix in inspector.get_indexes("projects")}
    assert "ix_projects_owner" in index_names


def test_projects_required_columns_not_nullable(tmp_path: Path) -> None:
    """Required columns are NOT NULL; the optional defaults are nullable."""
    by_name = {col["name"]: col for col in sa.inspect(_upgrade(tmp_path)).get_columns("projects")}
    for required in ("id", "owner", "name", "workspace", "created_at"):
        assert by_name[required]["nullable"] is False, required
    for optional in ("agent", "harness", "model", "updated_at"):
        assert by_name[optional]["nullable"] is True, optional


def test_projects_downgrade_drops_table(tmp_path: Path) -> None:
    """The migration's downgrade() removes the ``projects`` table."""
    uri = f"sqlite:///{tmp_path / 'projects.db'}"
    engine = sa.create_engine(uri)
    cfg = _alembic_cfg(uri)
    alembic_command.upgrade(cfg, _REVISION)
    assert "projects" in sa.inspect(engine).get_table_names()
    alembic_command.downgrade(cfg, _DOWN_REVISION)
    assert "projects" not in sa.inspect(engine).get_table_names()
