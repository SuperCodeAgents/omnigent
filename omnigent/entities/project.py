"""Project entity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Project:
    """
    A user-defined project: a named workspace plus launch defaults.

    A project groups work on one repository/directory. ``omnigent run
    --project <name>`` runs in the project's :attr:`workspace` and applies
    its default agent/harness/model, and the resulting session is tagged
    with the project name so it can be found again from any device.

    :param id: Unique project id, e.g. ``"proj_abc123"``.
    :param owner: Owning user id (the reserved ``"local"`` in single-user
        mode), e.g. ``"alice@example.com"``.
    :param name: Project name, unique per owner, e.g. ``"waypoint-api"``.
    :param workspace: Absolute path to the project's working directory.
    :param created_at: Unix epoch seconds of creation.
    :param agent: Default agent target (path or name), or ``None``.
    :param harness: Default harness id, e.g. ``"codex"``, or ``None``.
    :param model: Default model id, or ``None``.
    :param updated_at: Unix epoch seconds of the last update, or ``None``.
    """

    id: str
    owner: str
    name: str
    workspace: str
    created_at: int
    agent: str | None = None
    harness: str | None = None
    model: str | None = None
    updated_at: int | None = None
