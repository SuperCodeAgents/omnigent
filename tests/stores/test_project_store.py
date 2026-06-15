"""Unit tests for :class:`omnigent.stores.project_store.ProjectStore`."""

from __future__ import annotations

import pytest

from omnigent.stores.project_store import ProjectStore


@pytest.fixture()
def project_store(db_uri: str) -> ProjectStore:
    """A ProjectStore backed by the migrated test database."""
    return ProjectStore(db_uri)


def test_upsert_creates_then_updates_in_place(project_store: ProjectStore) -> None:
    """Re-upserting the same (owner, name) updates the row, keeping its id."""
    created = project_store.upsert(
        "alice", "api", "/src/api", agent="examples/polly", harness="codex"
    )
    assert created.id.startswith("proj_")
    assert created.workspace == "/src/api"
    assert created.agent == "examples/polly"
    assert created.harness == "codex"
    assert created.updated_at is None

    updated = project_store.upsert("alice", "api", "/src/api2", harness="claude-sdk")
    assert updated.id == created.id
    assert updated.workspace == "/src/api2"
    assert updated.harness == "claude-sdk"
    assert updated.agent is None  # omitted fields are cleared on update
    assert updated.updated_at is not None


def test_list_for_owner_is_scoped(project_store: ProjectStore) -> None:
    """A user sees only their own projects."""
    project_store.upsert("alice", "api", "/a")
    project_store.upsert("alice", "web", "/w")
    project_store.upsert("bob", "api", "/b")
    assert {p.name for p in project_store.list_for_owner("alice")} == {"api", "web"}
    assert [p.name for p in project_store.list_for_owner("bob")] == ["api"]
    assert project_store.list_for_owner("carol") == []


def test_list_for_owner_orders_newest_first(
    project_store: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Projects are listed newest-created first (the route's cursors rely on it)."""
    import omnigent.stores.project_store as project_store_module

    timestamps = iter([100, 200])
    monkeypatch.setattr(project_store_module, "now_epoch", lambda: next(timestamps))
    project_store.upsert("alice", "first", "/1")
    project_store.upsert("alice", "second", "/2")
    assert [p.name for p in project_store.list_for_owner("alice")] == ["second", "first"]


def test_get_by_name_scoped_to_owner(project_store: ProjectStore) -> None:
    """get_by_name never returns another owner's project."""
    project_store.upsert("alice", "api", "/a")
    got = project_store.get_by_name("alice", "api")
    assert got is not None
    assert got.name == "api"
    assert project_store.get_by_name("bob", "api") is None
    assert project_store.get_by_name("alice", "missing") is None


def test_delete_by_name(project_store: ProjectStore) -> None:
    """Delete is owner-scoped and idempotent-false on a missing project."""
    project_store.upsert("alice", "api", "/a")
    assert project_store.delete_by_name("bob", "api") is False
    assert project_store.delete_by_name("alice", "api") is True
    assert project_store.delete_by_name("alice", "api") is False
    assert project_store.get_by_name("alice", "api") is None
