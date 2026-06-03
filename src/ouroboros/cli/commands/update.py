"""Update command for Ouroboros local source installs.

Supports the Hermes-style fork workflow:
- origin = personal fork
- upstream = official Q00/ouroboros

The command updates the local checkout on the requested branch (default: main),
syncs the fork from upstream when safe, and refreshes the installed CLI via
``uv tool install --editable``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
import typer

from ouroboros.cli.formatters import console
from ouroboros.cli.formatters.panels import print_error, print_info, print_success, print_warning


PROJECT_ROOT = Path(__file__).resolve().parents[4]
OFFICIAL_REPO_URLS = {
    "https://github.com/Q00/ouroboros.git",
    "https://github.com/Q00/ouroboros",
    "git@github.com:Q00/ouroboros.git",
    "git@github.com:Q00/ouroboros",
}
OFFICIAL_REPO_URL = "git@github.com:Q00/ouroboros.git"


@dataclass
class UpdateContext:
    current_branch: str
    target_branch: str
    switched_branches: bool = False
    stash_ref: str | None = None


app = typer.Typer(
    name="update",
    help="Update a local Ouroboros source checkout and refresh the editable CLI install.",
    invoke_without_command=True,
)


def _normalize_remote_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _is_fork(origin_url: str | None) -> bool:
    normalized = _normalize_remote_url(origin_url)
    if not normalized:
        return False
    for official in OFFICIAL_REPO_URLS:
        if normalized == _normalize_remote_url(official):
            return False
    return True


def _git(*args: str, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=capture_output,
        check=check,
    )


def _git_output(*args: str) -> str:
    return _git(*args).stdout.strip()


def _remote_url(name: str) -> str | None:
    try:
        return _git_output("remote", "get-url", name)
    except subprocess.CalledProcessError:
        return None


def _has_remote(name: str) -> bool:
    return _remote_url(name) is not None


def _ensure_upstream_remote() -> None:
    if _has_remote("upstream"):
        return
    print_info("No upstream remote found; adding official upstream.")
    _git("remote", "add", "upstream", OFFICIAL_REPO_URL)
    print_success(f"Added upstream remote: {OFFICIAL_REPO_URL}")


def _count_commits(base: str, head: str) -> int:
    return int(_git_output("rev-list", "--count", f"{base}..{head}"))


def _stash_local_changes_if_needed() -> str | None:
    status = _git_output("status", "--porcelain")
    if not status:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    msg = f"ouroboros-update-autostash-{stamp}"
    _git("stash", "push", "-u", "-m", msg)
    stash_ref = _git_output("stash", "list", "--format=%gd", "-n", "1")
    print_info(f"Stashed local changes: {stash_ref}")
    return stash_ref or None


def _restore_stash(stash_ref: str | None) -> None:
    if not stash_ref:
        return
    try:
        _git("stash", "pop", stash_ref, check=True, capture_output=True)
        print_success(f"Restored stashed changes: {stash_ref}")
    except subprocess.CalledProcessError as exc:
        print_warning(
            "Could not auto-restore stashed changes. Restore manually with: "
            f"git -C {PROJECT_ROOT} stash pop {stash_ref}"
        )
        if exc.stderr.strip():
            console.print(exc.stderr.strip())


def _ensure_target_branch(target_branch: str) -> UpdateContext:
    current_branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    ctx = UpdateContext(current_branch=current_branch, target_branch=target_branch)
    if current_branch == target_branch:
        ctx.stash_ref = _stash_local_changes_if_needed()
        return ctx

    print_info(f"Switching from {current_branch} to {target_branch} for update.")
    ctx.stash_ref = _stash_local_changes_if_needed()
    checkout = subprocess.run(
        ["git", "checkout", target_branch],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    if checkout.returncode != 0:
        _git("checkout", "-B", target_branch, f"origin/{target_branch}")
    ctx.switched_branches = True
    return ctx


def _restore_branch(ctx: UpdateContext) -> None:
    if ctx.switched_branches and ctx.current_branch not in {ctx.target_branch, "HEAD"}:
        subprocess.run(
            ["git", "checkout", ctx.current_branch],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        print_info(f"Returned to branch: {ctx.current_branch}")
    _restore_stash(ctx.stash_ref)


def _sync_fork_with_upstream_if_safe(target_branch: str) -> None:
    if target_branch != "main":
        return
    _ensure_upstream_remote()
    print_info("Fetching upstream...")
    _git("fetch", "upstream", "--prune")

    origin_ahead = _count_commits("upstream/main", "origin/main")
    upstream_ahead = _count_commits("origin/main", "upstream/main")

    if origin_ahead > 0:
        print_warning(
            f"Fork has {origin_ahead} commit(s) not on upstream; skipping upstream fast-forward sync."
        )
        return
    if upstream_ahead == 0:
        print_success("Fork is already up to date with upstream.")
        return

    print_info(f"Fork is {upstream_ahead} commit(s) behind upstream; fast-forwarding local main.")
    _git("pull", "--ff-only", "upstream", "main")
    _git("push", "origin", "main")
    print_success("Synced fork main with upstream.")


def _pull_origin_if_needed(target_branch: str) -> bool:
    print_info("Fetching origin...")
    _git("fetch", "origin", "--prune")
    commits_behind = _count_commits("HEAD", f"origin/{target_branch}")
    if commits_behind == 0:
        print_success("Already up to date with origin.")
        return False
    print_info(f"Pulling {commits_behind} commit(s) from origin/{target_branch}...")
    _git("pull", "--ff-only", "origin", target_branch, capture_output=False)
    print_success("Updated local checkout from origin.")
    return True


def _reinstall_editable() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to refresh the editable Ouroboros install.")
    print_info("Refreshing editable CLI install...")
    subprocess.run([uv, "tool", "install", "--editable", str(PROJECT_ROOT), "--force"], check=True)
    print_success("Editable CLI install refreshed.")


@app.callback(invoke_without_command=True)
def update_command(
    ctx: typer.Context,
    branch: str = typer.Option("main", "--branch", help="Branch to update from origin."),
) -> None:
    """Update a fork-tracked Ouroboros checkout and refresh the installed CLI."""
    if ctx.invoked_subcommand is not None:
        return
    git_dir = PROJECT_ROOT / ".git"
    if not git_dir.exists():
        print_error(f"{PROJECT_ROOT} is not a git checkout.")
        raise typer.Exit(code=1)

    origin_url = _remote_url("origin")
    if not origin_url:
        print_error("No origin remote configured.")
        raise typer.Exit(code=1)

    local_ctx = _ensure_target_branch(branch)
    try:
        if _is_fork(origin_url):
            print_info(f"Detected fork origin: {origin_url}")
            _sync_fork_with_upstream_if_safe(branch)
        updated = _pull_origin_if_needed(branch)
        if updated:
            _reinstall_editable()
            print_success("Ouroboros update complete.")
        else:
            print_info("No code changes pulled; skipped reinstall.")
    finally:
        _restore_branch(local_ctx)


__all__ = [
    "app",
    "update_command",
    "_normalize_remote_url",
    "_is_fork",
    "_ensure_upstream_remote",
    "_sync_fork_with_upstream_if_safe",
]
