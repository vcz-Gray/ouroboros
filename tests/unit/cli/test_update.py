from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ouroboros.cli.commands import update as update_cmd
from ouroboros.cli.main import app


runner = CliRunner()


def test_update_help_registered() -> None:
    result = runner.invoke(app, ["update", "--help"])
    assert result.exit_code == 0
    assert "editable CLI install" in result.output
    assert "--branch" in result.output


def test_is_fork_detects_official_urls() -> None:
    assert update_cmd._is_fork("https://github.com/Q00/ouroboros.git") is False
    assert update_cmd._is_fork("git@github.com:Q00/ouroboros.git") is False
    assert update_cmd._is_fork("git@github.com:vcz-Gray/ouroboros.git") is True


def test_sync_fork_with_upstream_if_safe_fast_forwards(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str, **kwargs):
        calls.append(tuple(args))
        return MagicMock(stdout="", returncode=0)

    monkeypatch.setattr(update_cmd, "_ensure_upstream_remote", lambda: calls.append(("ensure_upstream",)))
    monkeypatch.setattr(update_cmd, "_git", fake_git)
    monkeypatch.setattr(
        update_cmd,
        "_count_commits",
        lambda base, head: 0 if (base, head) == ("upstream/main", "origin/main") else 2,
    )

    update_cmd._sync_fork_with_upstream_if_safe("main")

    assert ("ensure_upstream",) in calls
    assert ("fetch", "upstream", "--prune") in calls
    assert ("pull", "--ff-only", "upstream", "main") in calls
    assert ("push", "origin", "main") in calls


def test_update_command_skips_reinstall_when_origin_is_current(monkeypatch, tmp_path: Path) -> None:
    fake_git_dir = tmp_path / ".git"
    fake_git_dir.mkdir()
    monkeypatch.setattr(update_cmd, "PROJECT_ROOT", tmp_path)

    ctx_obj = update_cmd.UpdateContext(current_branch="main", target_branch="main")

    monkeypatch.setattr(update_cmd, "_remote_url", lambda name: "git@github.com:Q00/ouroboros.git")
    monkeypatch.setattr(update_cmd, "_ensure_target_branch", lambda branch: ctx_obj)
    monkeypatch.setattr(update_cmd, "_pull_origin_if_needed", lambda branch: False)
    monkeypatch.setattr(update_cmd, "_restore_branch", lambda ctx: None)

    reinstall_called = False

    def fake_reinstall() -> None:
        nonlocal reinstall_called
        reinstall_called = True

    monkeypatch.setattr(update_cmd, "_reinstall_editable", fake_reinstall)

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert reinstall_called is False
    assert "skipped reinstall" in result.output.lower()


def test_update_command_reinstalls_when_pull_applies(monkeypatch, tmp_path: Path) -> None:
    fake_git_dir = tmp_path / ".git"
    fake_git_dir.mkdir()
    monkeypatch.setattr(update_cmd, "PROJECT_ROOT", tmp_path)

    ctx_obj = update_cmd.UpdateContext(current_branch="main", target_branch="main")

    monkeypatch.setattr(update_cmd, "_remote_url", lambda name: "git@github.com:Q00/ouroboros.git")
    monkeypatch.setattr(update_cmd, "_ensure_target_branch", lambda branch: ctx_obj)
    monkeypatch.setattr(update_cmd, "_pull_origin_if_needed", lambda branch: True)
    monkeypatch.setattr(update_cmd, "_restore_branch", lambda ctx: None)

    with patch("ouroboros.cli.commands.update._reinstall_editable") as reinstall_mock:
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    reinstall_mock.assert_called_once_with()
    assert "update complete" in result.output.lower()
