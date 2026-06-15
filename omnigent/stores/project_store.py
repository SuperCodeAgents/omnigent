"""Persistent store for user-defined projects.

A project is a named workspace plus launch defaults (agent/harness/model)
owned by a user. The ``projects`` table is the source of truth for
``GET /v1/projects`` so a user's projects are visible from any device that
connects to the same server. ``owner`` is a plain user-id string (the
reserved ``"local"`` in single-user mode); every read and write filters on
it so one user never sees another's projects.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, select

from omnigent.db.db_models import SqlProject
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities import Project


def _row_to_project(row: SqlProject) -> Project:
    """Convert a ``projects`` row into a :class:`Project` entity."""
    return Project(
        id=row.id,
        owner=row.owner,
        name=row.name,
        workspace=row.workspace,
        agent=row.agent,
        harness=row.harness,
        model=row.model,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ProjectStore:
    """Persistent store for user-defined projects backed by SQLAlchemy.

    :param storage_location: SQLAlchemy database URI, e.g.
        ``"sqlite:///omnigent.db"``.
    """

    def __init__(self, storage_location: str) -> None:
        """Initialize the project store.

        :param storage_location: SQLAlchemy database URI.
        """
        self._engine: Engine = get_or_create_engine(storage_location)
        # immediate=True takes the write lock before the upsert's check-then-act
        # SELECT, so two concurrent creates of the same (owner, name) can't both
        # miss and then collide on the unique constraint (a same-user retry from
        # two devices is exactly this feature's scenario).
        self._session = make_managed_session_maker(self._engine, immediate=True)

    def upsert(
        self,
        owner: str,
        name: str,
        workspace: str,
        *,
        agent: str | None = None,
        harness: str | None = None,
        model: str | None = None,
    ) -> Project:
        """Create a project, or replace the existing one with the same name.

        Idempotent per ``(owner, name)``: re-running ``project add`` edits the
        existing project rather than failing. This is a **full replace** — the
        stored row is set to exactly the values passed here, so an omitted
        ``agent`` / ``harness`` / ``model`` clears any previously stored value.

        :param owner: Owning user id.
        :param name: Project name (unique per owner).
        :param workspace: Absolute path to the project's working directory.
        :param agent: Default agent target, or ``None``.
        :param harness: Default harness id, or ``None``.
        :param model: Default model id, or ``None``.
        :returns: The created or updated project.
        """
        with self._session() as session:
            row = session.execute(
                select(SqlProject).where(SqlProject.owner == owner, SqlProject.name == name)
            ).scalar_one_or_none()
            if row is None:
                row = SqlProject(
                    id=f"proj_{uuid.uuid4().hex}",
                    owner=owner,
                    name=name,
                    workspace=workspace,
                    agent=agent,
                    harness=harness,
                    model=model,
                    created_at=now_epoch(),
                )
                session.add(row)
            else:
                row.workspace = workspace
                row.agent = agent
                row.harness = harness
                row.model = model
                row.updated_at = now_epoch()
            return _row_to_project(row)

    def list_for_owner(self, owner: str) -> list[Project]:
        """List a user's projects, newest first.

        :param owner: Owning user id.
        :returns: The owner's projects, ordered by creation time descending.
        """
        with self._session() as session:
            rows = (
                session.execute(
                    select(SqlProject)
                    .where(SqlProject.owner == owner)
                    .order_by(SqlProject.created_at.desc(), SqlProject.id.desc())
                )
                .scalars()
                .all()
            )
            return [_row_to_project(row) for row in rows]

    def get_by_name(self, owner: str, name: str) -> Project | None:
        """Fetch one of a user's projects by name.

        :param owner: Owning user id.
        :param name: Project name.
        :returns: The project, or ``None`` when the owner has no such project.
        """
        with self._session() as session:
            row = session.execute(
                select(SqlProject).where(SqlProject.owner == owner, SqlProject.name == name)
            ).scalar_one_or_none()
            return _row_to_project(row) if row is not None else None

    def delete_by_name(self, owner: str, name: str) -> bool:
        """Delete one of a user's projects by name.

        :param owner: Owning user id.
        :param name: Project name.
        :returns: ``True`` if a project was deleted, ``False`` if none matched.
        """
        with self._session() as session:
            row = session.execute(
                select(SqlProject).where(SqlProject.owner == owner, SqlProject.name == name)
            ).scalar_one_or_none()
            if row is None:
                return False
            session.delete(row)
            return True
