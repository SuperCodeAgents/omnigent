"""Tests for the ``omnigent project`` commands and ``run --project``.

CLI behavior is exercised with ``CliRunner`` and a monkeypatched network seam
(``omnigent.cli._host_http_json`` / ``_fetch_session_pages``) plus a stubbed
server resolver — no live server. ``run --project`` stubs ``run_chat`` to
assert the resolved defaults and project label are threaded through.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from omnigent import cli
from omnigent.cli import cli as cli_group


def _stub_server(monkeypatch: pytest.MonkeyPatch, url: str | None = "http://test.local") -> None:
    """Force project commands to resolve *url* as their server."""
    monkeypatch.setattr("omnigent.cli._resolve_host_server", lambda _server: url)
    monkeypatch.setattr("omnigent.cli.local_server_url_if_healthy", lambda: None)
    monkeypatch.setattr("omnigent.cli._load_effective_config", dict)


def test_project_add_posts_resolved_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`project add` resolves the workspace to an absolute path and POSTs it."""
    _stub_server(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake(*, method: str, path: str, json_body: Any = None, **_kw: Any) -> cli._HostHttpResult:
        calls.append({"method": method, "path": path, "json_body": json_body})
        return cli._HostHttpResult(status_code=200, body={"id": "proj_1", "name": "wp"})

    monkeypatch.setattr("omnigent.cli._host_http_json", fake)
    workspace = tmp_path / "wp"
    workspace.mkdir()

    result = CliRunner().invoke(
        cli_group, ["project", "add", "wp", "--workspace", str(workspace), "--harness", "codex"]
    )

    assert result.exit_code == 0, result.output
    post = next(c for c in calls if c["path"] == "/v1/projects")
    assert post["method"] == "POST"
    assert post["json_body"]["name"] == "wp"
    assert post["json_body"]["workspace"] == str(workspace.resolve())
    assert post["json_body"]["harness"] == "codex"


def test_project_add_defaults_workspace_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without --workspace, the current directory is used."""
    _stub_server(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake(*, json_body: Any = None, **_kw: Any) -> cli._HostHttpResult:
        calls.append({"json_body": json_body})
        return cli._HostHttpResult(status_code=200, body={"id": "p", "name": "n"})

    monkeypatch.setattr("omnigent.cli._host_http_json", fake)
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = CliRunner().invoke(cli_group, ["project", "add", "n"])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert calls[0]["json_body"]["workspace"] == str(tmp_path.resolve())


def test_project_list_renders_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project list` prints each project with its workspace and extras."""
    _stub_server(monkeypatch)
    body: Any = {
        "object": "list",
        "data": [
            {"name": "wp", "workspace": "/src/wp", "harness": "codex"},
            {"name": "web", "workspace": "/src/web"},
        ],
    }
    monkeypatch.setattr(
        "omnigent.cli._host_http_json",
        lambda **_kw: cli._HostHttpResult(status_code=200, body=body),
    )

    result = CliRunner().invoke(cli_group, ["project", "list"])

    assert result.exit_code == 0, result.output
    assert "wp" in result.output
    assert "/src/wp" in result.output
    assert "harness=codex" in result.output
    assert "web" in result.output


def test_project_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project list` with no projects prints a helpful hint."""
    _stub_server(monkeypatch)
    monkeypatch.setattr(
        "omnigent.cli._host_http_json",
        lambda **_kw: cli._HostHttpResult(status_code=200, body={"data": []}),
    )

    result = CliRunner().invoke(cli_group, ["project", "list"])

    assert result.exit_code == 0, result.output
    assert "No projects yet" in result.output


def test_project_show_missing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project show` on a 404 surfaces a clean 'no project named' error."""
    _stub_server(monkeypatch)
    monkeypatch.setattr(
        "omnigent.cli._host_http_json",
        lambda **_kw: cli._HostHttpResult(status_code=404, body={"error": {"code": "not_found"}}),
    )

    result = CliRunner().invoke(cli_group, ["project", "show", "ghost"])

    assert result.exit_code != 0
    assert "No project named 'ghost'" in result.output


def test_project_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project remove` issues a DELETE and confirms."""
    _stub_server(monkeypatch)
    seen: list[str] = []

    def fake(*, method: str, path: str, **_kw: Any) -> cli._HostHttpResult:
        seen.append(f"{method} {path}")
        return cli._HostHttpResult(status_code=200, body={"deleted": True})

    monkeypatch.setattr("omnigent.cli._host_http_json", fake)

    result = CliRunner().invoke(cli_group, ["project", "remove", "wp"])

    assert result.exit_code == 0, result.output
    assert "DELETE /v1/projects/wp" in seen
    assert "Removed project 'wp'" in result.output


def test_project_sessions_filters_by_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project sessions` shows only sessions tagged with the project."""
    _stub_server(monkeypatch)
    rows: list[dict[str, Any]] = [
        {"id": "conv_1", "title": "fix auth", "status": "running", "labels": {"project": "wp"}},
        {"id": "conv_2", "title": "other", "status": "idle", "labels": {"project": "web"}},
        {"id": "conv_3", "title": "untagged", "status": "idle"},
    ]
    monkeypatch.setattr(
        "omnigent.cli._fetch_session_pages",
        lambda **_kw: cli._SessionPagesResult(sessions=rows, error=None),
    )

    result = CliRunner().invoke(cli_group, ["project", "sessions", "wp"])

    assert result.exit_code == 0, result.output
    assert "conv_1" in result.output
    assert "conv_2" not in result.output
    assert "conv_3" not in result.output


def test_project_sessions_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`project sessions` with no matches prints a clear message."""
    _stub_server(monkeypatch)
    monkeypatch.setattr(
        "omnigent.cli._fetch_session_pages",
        lambda **_kw: cli._SessionPagesResult(sessions=[], error=None),
    )

    result = CliRunner().invoke(cli_group, ["project", "sessions", "wp"])

    assert result.exit_code == 0, result.output
    assert "No sessions found for project 'wp'" in result.output


def _stub_project_for_run(monkeypatch: pytest.MonkeyPatch, project: dict[str, Any]) -> Mock:
    """Wire `run --project` to resolve *project* and capture the run_chat call."""
    # run --project ensures a backend (spawning a local server on a cold start);
    # stub it so the test never touches a real server.
    monkeypatch.setattr("omnigent.cli._ensure_backend", lambda _server: "http://test.local")
    monkeypatch.setattr("omnigent.cli._load_effective_config", dict)
    monkeypatch.setattr(
        "omnigent.cli._host_http_json",
        lambda **_kw: cli._HostHttpResult(status_code=200, body=project),
    )
    run_chat = Mock()
    monkeypatch.setattr("omnigent.chat.run_chat", run_chat)
    return run_chat


def test_run_project_applies_defaults_and_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run --project` applies the project's agent/harness and tags the session."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_chat = _stub_project_for_run(
        monkeypatch,
        {"name": "wp", "workspace": str(workspace), "agent": "examples/polly", "harness": "codex"},
    )

    original = os.getcwd()
    try:
        result = CliRunner().invoke(cli_group, ["run", "--project", "wp", "-p", "hi"])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    run_chat.assert_called_once()
    kwargs = run_chat.call_args.kwargs
    assert kwargs["project_label"] == "wp"
    assert kwargs["harness"] == "codex"
    assert kwargs["target"] == "examples/polly"


def test_run_explicit_flag_overrides_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit --harness wins over the project's default harness."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_chat = _stub_project_for_run(
        monkeypatch,
        {"name": "wp", "workspace": str(workspace), "agent": "examples/polly", "harness": "codex"},
    )

    original = os.getcwd()
    try:
        result = CliRunner().invoke(
            cli_group, ["run", "--project", "wp", "--harness", "pi", "-p", "hi"]
        )
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert run_chat.call_args.kwargs["harness"] == "pi"


def test_run_project_applies_model_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The project's default model is applied when --model is not passed."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_chat = _stub_project_for_run(
        monkeypatch, {"name": "wp", "workspace": str(workspace), "model": "gpt-5"}
    )

    original = os.getcwd()
    try:
        result = CliRunner().invoke(cli_group, ["run", "--project", "wp", "-p", "hi"])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert run_chat.call_args.kwargs["model"] == "gpt-5"


def test_run_explicit_model_overrides_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit --model wins over the project's default model."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_chat = _stub_project_for_run(
        monkeypatch, {"name": "wp", "workspace": str(workspace), "model": "gpt-5"}
    )

    original = os.getcwd()
    try:
        result = CliRunner().invoke(
            cli_group, ["run", "--project", "wp", "--model", "claude-opus", "-p", "hi"]
        )
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert run_chat.call_args.kwargs["model"] == "claude-opus"


def test_run_project_missing_workspace_errors_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A workspace that doesn't exist on this machine fails with a clean error."""
    missing = tmp_path / "does-not-exist"
    run_chat = _stub_project_for_run(monkeypatch, {"name": "wp", "workspace": str(missing)})

    original = os.getcwd()
    try:
        result = CliRunner().invoke(cli_group, ["run", "--project", "wp", "-p", "hi"])
    finally:
        os.chdir(original)

    assert result.exit_code != 0
    assert "not accessible on this machine" in result.output
    run_chat.assert_not_called()


@pytest.mark.parametrize("mode_flag", ["--continue", "--no-session", ["--fork", "conv_x"]])
def test_run_project_rejects_incompatible_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode_flag: object
) -> None:
    """--project cannot be combined with resume/continue/fork/no-session."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_chat = _stub_project_for_run(monkeypatch, {"name": "wp", "workspace": str(workspace)})
    extra = mode_flag if isinstance(mode_flag, list) else [mode_flag]

    result = CliRunner().invoke(cli_group, ["run", "--project", "wp", *extra, "-p", "hi"])

    assert result.exit_code != 0
    assert "can't be combined" in result.output
    run_chat.assert_not_called()
