"""Routes for user-defined projects (``/v1/projects``).

CRUD for per-user projects — a named workspace plus launch defaults
(agent/harness/model). Every project is owned by the authenticated caller
(the reserved ``"local"`` in single-user mode); all reads and writes are
scoped to that owner so one user never sees another's projects. Storing
projects on the server (rather than only in local CLI config) is what makes
them visible from any device connected to the same server.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from omnigent.entities import Project
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user as _require_user
from omnigent.server.schemas import PaginatedList, ProjectCreateRequest, ProjectObject
from omnigent.stores.project_store import ProjectStore

# Owner used when auth is disabled (single-user mode), mirroring the host
# routes' fallback so a project can be created without a signed-in user.
_LOCAL_OWNER = "local"


def _to_project_object(project: Project) -> ProjectObject:
    """Convert a stored :class:`Project` into its API representation."""
    return ProjectObject(
        id=project.id,
        name=project.name,
        workspace=project.workspace,
        agent=project.agent,
        harness=project.harness,
        model=project.model,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def create_projects_router(
    project_store: ProjectStore,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build the router for ``/v1/projects``.

    Mounted with ``prefix="/v1"`` so the final paths are ``/v1/projects``
    and ``/v1/projects/{name}``.

    :param project_store: Store backing project CRUD.
    :param auth_provider: Auth provider; when set, callers must be
        authenticated and every project is scoped to their identity.
    :returns: A configured :class:`APIRouter`.
    """
    router = APIRouter()

    def _owner(request: Request) -> str:
        """Resolve the owner (``"local"`` when auth is disabled)."""
        return _require_user(request, auth_provider) or _LOCAL_OWNER

    @router.get("/projects")
    async def list_projects(request: Request) -> PaginatedList:
        """List the caller's projects, newest first."""
        owner = _owner(request)
        projects = await asyncio.to_thread(project_store.list_for_owner, owner)
        data = [_to_project_object(p) for p in projects]
        return PaginatedList(
            data=data,
            first_id=data[0].id if data else None,
            last_id=data[-1].id if data else None,
            has_more=False,
        )

    @router.post("/projects")
    async def upsert_project(request: Request, body: ProjectCreateRequest) -> ProjectObject:
        """Create a project, or update the existing one with the same name."""
        owner = _owner(request)
        project = await asyncio.to_thread(
            project_store.upsert,
            owner,
            body.name,
            body.workspace,
            agent=body.agent,
            harness=body.harness,
            model=body.model,
        )
        return _to_project_object(project)

    @router.get("/projects/{name}")
    async def get_project(request: Request, name: str) -> ProjectObject:
        """Fetch one of the caller's projects by name.

        :raises OmnigentError: 404 when the caller has no such project.
        """
        owner = _owner(request)
        project = await asyncio.to_thread(project_store.get_by_name, owner, name)
        if project is None:
            raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
        return _to_project_object(project)

    @router.delete("/projects/{name}")
    async def delete_project(request: Request, name: str) -> dict[str, bool]:
        """Delete one of the caller's projects by name.

        :raises OmnigentError: 404 when the caller has no such project.
        """
        owner = _owner(request)
        deleted = await asyncio.to_thread(project_store.delete_by_name, owner, name)
        if not deleted:
            raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
        return {"deleted": True}

    return router
