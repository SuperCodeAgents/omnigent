"""Route tests for ``/v1/projects``.

The shared ``client`` fixture (``tests/server/conftest.py``) now wires a
``project_store``, so ``/v1/projects`` is mounted there with single-user
``"local"`` ownership. A separate header-auth app exercises owner scoping.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store import ProjectStore


async def test_create_list_get_delete(client: httpx.AsyncClient) -> None:
    """The full CRUD lifecycle of a project."""
    create = await client.post(
        "/v1/projects",
        json={"name": "waypoint-api", "workspace": "/src/wp", "harness": "codex"},
    )
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["object"] == "project"
    assert body["name"] == "waypoint-api"
    assert body["workspace"] == "/src/wp"
    assert body["harness"] == "codex"
    assert body["id"].startswith("proj_")

    listing = await client.get("/v1/projects")
    assert listing.status_code == 200
    assert listing.json()["object"] == "list"
    assert body["id"] in [p["id"] for p in listing.json()["data"]]

    got = await client.get("/v1/projects/waypoint-api")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]

    deleted = await client.delete("/v1/projects/waypoint-api")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert (await client.get("/v1/projects/waypoint-api")).status_code == 404


async def test_post_upserts_by_name(client: httpx.AsyncClient) -> None:
    """POSTing an existing name updates it in place rather than duplicating."""
    first = await client.post("/v1/projects", json={"name": "p", "workspace": "/a"})
    second = await client.post(
        "/v1/projects", json={"name": "p", "workspace": "/b", "model": "gpt-5"}
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["workspace"] == "/b"
    assert second.json()["model"] == "gpt-5"
    listing = await client.get("/v1/projects")
    assert sum(1 for p in listing.json()["data"] if p["name"] == "p") == 1


async def test_missing_project_is_404(client: httpx.AsyncClient) -> None:
    """GET/DELETE of an unknown project return 404."""
    assert (await client.get("/v1/projects/nope")).status_code == 404
    assert (await client.delete("/v1/projects/nope")).status_code == 404


async def test_invalid_name_and_missing_workspace_rejected(client: httpx.AsyncClient) -> None:
    """A bad name or absent workspace fails request validation (422)."""
    assert (
        await client.post("/v1/projects", json={"name": "bad name!", "workspace": "/a"})
    ).status_code == 422
    assert (await client.post("/v1/projects", json={"name": "ok"})).status_code == 422


async def test_dotted_name_accepted(client: httpx.AsyncClient) -> None:
    """A name with a dot (e.g. 'api.v2') is valid and round-trips."""
    resp = await client.post("/v1/projects", json={"name": "api.v2", "workspace": "/a"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "api.v2"


@pytest.fixture()
def auth_app(db_uri: str, tmp_path: Path) -> FastAPI:
    """A project-enabled app with header auth so requests are owner-scoped."""
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    return create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        permission_store=SqlAlchemyPermissionStore(db_uri),
        project_store=ProjectStore(db_uri),
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=True),
    )


@pytest_asyncio.fixture()
async def auth_client(auth_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An async client wired to the header-auth project app."""
    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_projects_are_owner_scoped(auth_client: httpx.AsyncClient) -> None:
    """One user never sees or fetches another user's projects."""
    alice = {"X-Forwarded-Email": "alice@example.com"}
    bob = {"X-Forwarded-Email": "bob@example.com"}
    created = await auth_client.post(
        "/v1/projects", json={"name": "secret", "workspace": "/a"}, headers=alice
    )
    assert created.status_code == 200

    assert (await auth_client.get("/v1/projects", headers=bob)).json()["data"] == []
    assert (await auth_client.get("/v1/projects/secret", headers=bob)).status_code == 404
    # Bob also cannot delete Alice's project (404, and it survives).
    assert (await auth_client.delete("/v1/projects/secret", headers=bob)).status_code == 404
    assert (await auth_client.get("/v1/projects/secret", headers=alice)).status_code == 200

    alice_list = await auth_client.get("/v1/projects", headers=alice)
    assert [p["name"] for p in alice_list.json()["data"]] == ["secret"]


@pytest.fixture()
def strict_auth_app(db_uri: str, tmp_path: Path) -> FastAPI:
    """A project app in true multi-user mode (no single-user fallback)."""
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    return create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        permission_store=SqlAlchemyPermissionStore(db_uri),
        project_store=ProjectStore(db_uri),
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
    )


@pytest_asyncio.fixture()
async def strict_auth_client(strict_auth_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An async client wired to the strict multi-user project app."""
    transport = httpx.ASGITransport(app=strict_auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_unauthenticated_request_rejected_in_multiuser(
    strict_auth_client: httpx.AsyncClient,
) -> None:
    """With no single-user fallback, a request with no identity is 401 (not 'local')."""
    assert (await strict_auth_client.get("/v1/projects")).status_code == 401
    assert (
        await strict_auth_client.post("/v1/projects", json={"name": "p", "workspace": "/a"})
    ).status_code == 401
